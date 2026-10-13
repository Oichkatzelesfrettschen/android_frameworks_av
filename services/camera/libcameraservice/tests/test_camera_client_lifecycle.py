"""Exercise production HAL1 client and torch lifecycle error paths."""

import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(
    os.environ.get("CAMERA_LIFECYCLE_SOURCE", Path(__file__).resolve().parents[4])
)


def method(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


PREFIX = r"""
#include <cassert>
#include <cerrno>
#include <memory>
#include <string>
#define LOG1(...) ((void)sizeof(callingPid))
#define ALOGE(...) ((void)0)
using status_t=int;
using String8=std::string;
inline constexpr int NO_ERROR=0, OK=0, INVALID_OPERATION=-38, BAD_INDEX=-75;
inline constexpr int NATIVE_WINDOW_SCALING_MODE_SCALE_TO_WINDOW=1;
static constexpr int callingPid=42;
namespace CameraThreadState { int getCallingPid() { return callingPid; } }
template<class Type> struct sp:std::shared_ptr<Type> {
    using std::shared_ptr<Type>::shared_ptr;
    sp(Type* value):std::shared_ptr<Type>(value) {}
    void clear() { this->reset(); }
};
struct Mutex { struct Autolock { explicit Autolock(Mutex&) {} }; };
struct Hardware {
    bool recording=false, preview=false;
    int installStatus=0, startStatus=0, starts=0, stops=0, installs=0;
    bool recordingEnabled() { return recording; }
    bool previewEnabled() { return preview; }
    void setPreviewScalingMode(int) {}
    void setPreviewTransform(int) {}
    int setPreviewWindow(int) { ++installs; return installStatus; }
    int startPreview() { ++starts; return startStatus; }
    void stopPreview() { ++stops; }
};
struct CameraClient {
    Mutex mLock;
    sp<Hardware> mHardware=new Hardware;
    sp<int> mRemoteCallback=new int(1);
    int mClientPid=42, mPreviewWindow=1, mOrientation=0, pidStatus=0, activeStatus=0, activeCalls=0;
    int checkPid() { return pidStatus; }
    int checkPidAndHardware() { return mHardware ? checkPid() : INVALID_OPERATION; }
    int notifyActive() { ++activeCalls; return activeStatus; }
    status_t unlock();
    status_t startPreviewMode();
};
enum class TorchModeStatus { AVAILABLE_OFF, AVAILABLE_ON };
struct Callbacks { int notifications=0; void onTorchStatusChanged(const String8&,TorchModeStatus) { ++notifications; } };
struct CameraHardwareInterfaceFlashControl {
    Mutex mLock;
    bool mTorchEnabled=false, flash=true;
    String8 mCameraId="0";
    sp<int> mDevice=new int(1);
    Callbacks callbacks;
    Callbacks* mCallbacks=&callbacks;
    int queries=0, starts=0, disconnects=0, startStatus=0;
    int hasFlashUnitLocked(const String8& name,bool* result,bool) {
        ++queries; if(name!=mCameraId) return BAD_INDEX; *result=flash; return 0;
    }
    void disconnectCameraDevice() { ++disconnects; mDevice.clear(); }
    int startPreviewAndTorch() { ++starts; return startStatus; }
    status_t setTorchMode(const String8&,bool);
};
"""


class CameraClientLifecycleTest(unittest.TestCase):
    def compile_case(self, name, code):
        output = Path(os.environ["TEST_OUTPUT_DIR"]).resolve(strict=True)
        source, binary = output / (name + ".cpp"), output / name
        source.write_text(PREFIX + code)
        subprocess.run(
            [
                os.environ.get("CXX", "c++"),
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-fsanitize=address,undefined",
                "-fno-sanitize-recover=all",
                str(source),
                "-o",
                str(binary),
            ],
            check=True,
        )
        subprocess.run([str(binary)], check=True)

    def test_unlock_rejects_disconnected_recording_and_wrong_owner(self):
        source = (
            ROOT / "services/camera/libcameraservice/api1/CameraClient.cpp"
        ).read_text()
        self.compile_case(
            "unlock-lifecycle",
            method(source, "status_t CameraClient::unlock()")
            + r"""
int main() {
    CameraClient disconnected; disconnected.mHardware.clear();
    assert(disconnected.unlock()==INVALID_OPERATION);
    assert(disconnected.mClientPid==42 && disconnected.mRemoteCallback);
    CameraClient recording; recording.mHardware->recording=true;
    assert(recording.unlock()==INVALID_OPERATION && recording.mClientPid==42);
    CameraClient wrong; wrong.pidStatus=EBUSY;
    assert(wrong.unlock()==EBUSY && wrong.mRemoteCallback);
    CameraClient valid;
    assert(valid.unlock()==0 && valid.mClientPid==0 && !valid.mRemoteCallback);
}
""",
        )

    def test_initial_window_failure_prevents_preview_and_active_notification(self):
        source = (
            ROOT / "services/camera/libcameraservice/api1/CameraClient.cpp"
        ).read_text()
        self.compile_case(
            "preview-install",
            method(source, "status_t CameraClient::startPreviewMode()")
            + r"""
int main() {
    for (int target : {0,1}) {
        CameraClient failed; failed.mPreviewWindow=target; failed.mHardware->installStatus=-5;
        assert(failed.startPreviewMode()==-5);
        assert(failed.mHardware->starts==0 && failed.activeCalls==0);
    }
    CameraClient failedStart; failedStart.mHardware->startStatus=-6;
    assert(failedStart.startPreviewMode()==-6 && failedStart.activeCalls==0);
    CameraClient refused; refused.activeStatus=-7;
    assert(refused.startPreviewMode()==-7 && refused.mHardware->stops==1);
    CameraClient valid;
    assert(valid.startPreviewMode()==0 && valid.mHardware->starts==1 && valid.activeCalls==1);
    CameraClient active; active.mHardware->preview=true;
    assert(active.startPreviewMode()==0 && active.mHardware->installs==0 && active.mHardware->starts==0 && active.activeCalls==1);
}
""",
        )

    def test_repeated_torch_enable_preserves_running_device(self):
        source = (
            ROOT / "services/camera/libcameraservice/CameraFlashlight.cpp"
        ).read_text()
        self.compile_case(
            "torch-repeat",
            method(
                source, "status_t CameraHardwareInterfaceFlashControl::setTorchMode("
            )
            + r"""
int main() {
    CameraHardwareInterfaceFlashControl control;
    assert(control.setTorchMode("0",true)==OK && control.mTorchEnabled);
    assert(control.starts==1 && control.callbacks.notifications==1);
    control.startStatus=-5;
    assert(control.setTorchMode("0",true)==OK && control.mTorchEnabled);
    assert(control.starts==1 && control.disconnects==0 && control.callbacks.notifications==1);
    assert(control.setTorchMode("1",true)==BAD_INDEX && control.mTorchEnabled);
    assert(control.setTorchMode("1",false)==OK && control.mTorchEnabled);
    assert(control.setTorchMode("0",false)==OK && !control.mTorchEnabled && control.disconnects==1);
    CameraHardwareInterfaceFlashControl failed; failed.startStatus=-5;
    assert(failed.setTorchMode("0",true)==-5 && failed.disconnects==1 && !failed.mTorchEnabled);
}
""",
        )


if __name__ == "__main__":
    unittest.main()
