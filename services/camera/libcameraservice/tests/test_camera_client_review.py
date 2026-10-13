"""Exercise production camera stop/callback and preview-target transitions."""

import os
import re
from pathlib import Path
import subprocess
import unittest

CHECKOUT = Path(__file__).resolve().parents[4]
SOURCE = Path(os.environ.get("CAMERA_CLIENT_SOURCE", CHECKOUT))


def body(source, signature):
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
#include <cstdint>
#include <cstring>
#include <functional>
#include <memory>
#include <mutex>
#include <vector>
#include <fcntl.h>
#include <unistd.h>
#define ALOGV(...) ((void)0)
#define ALOGW(...) ((void)0)
#define ALOGE(...) ((void)0)
#define LOG1(...) ((void)0)
using nsecs_t = int64_t;
using status_t = int;
constexpr int NO_ERROR=0, NO_INIT=-19, NATIVE_WINDOW_API_CAMERA=1, NATIVE_WINDOW_SCALING_MODE_SCALE_TO_WINDOW=1;
template<class T> class sp : public std::shared_ptr<T> {
public:
    using std::shared_ptr<T>::shared_ptr;
    sp() = default;
    sp(T* value): std::shared_ptr<T>(value) {}
    sp(std::shared_ptr<T> value): std::shared_ptr<T>(value) {}
    sp& operator=(T* value) { this->reset(value); return *this; }
    void clear() { this->reset(); }
};
template<class T> struct wp {
    std::weak_ptr<T> value;
    wp(const sp<T>& pointer):value(pointer) {}
    sp<T> promote() { return value.lock(); }
};
struct Mutex { std::mutex value; struct Autolock {
    std::lock_guard<std::mutex> lock;
    explicit Autolock(Mutex& mutex):lock(mutex.value) {}
}; };
struct IMemory {};
struct native_handle_t { int descriptor; };
static int closedHandles, deletedHandles;
int native_handle_close(native_handle_t* handle) {
    if (handle==nullptr) return 0;
    assert(close(handle->descriptor)==0); ++closedHandles; return 0;
}
int native_handle_delete(native_handle_t* handle) {
    if (handle!=nullptr) { ++deletedHandles; delete handle; }
    return 0;
}
[[maybe_unused]] static native_handle_t* makeHandle(int* peer, int* descriptor) {
    int descriptors[2]; assert(pipe(descriptors)==0);
    *peer=descriptors[1]; *descriptor=descriptors[0];
    return new native_handle_t{descriptors[0]};
}
namespace android { namespace hardware {
struct ICamera {
    int memories=0, handles=0, batches=0, stops=0, starts=0;
    std::function<void()> duringStop;
    virtual ~ICamera() = default;
    void releaseRecordingFrame(const sp<IMemory>&) { ++memories; }
    void releaseRecordingFrameHandle(native_handle_t* handle) {
        ++handles; native_handle_close(handle); native_handle_delete(handle);
    }
    void releaseRecordingFrameHandleBatch(const std::vector<native_handle_t*>& values) {
        ++batches;
        for (auto* handle:values) releaseRecordingFrameHandle(handle);
    }
    int startRecording() { ++starts; return NO_ERROR; }
    void stopRecording() { ++stops; if(duringStop) duringStop(); }
};
} }
struct ICameraRecordingProxyListener {
    virtual ~ICameraRecordingProxyListener() = default;
    virtual void dataCallbackTimestamp(nsecs_t,int32_t,const sp<IMemory>&)=0;
    virtual void recordingFrameHandleCallbackTimestamp(nsecs_t,native_handle_t*)=0;
    virtual void recordingFrameHandleCallbackTimestampBatch(const std::vector<nsecs_t>&,
                                                           const std::vector<native_handle_t*>&)=0;
};
struct BnCameraRecordingProxyListener: ICameraRecordingProxyListener {};
struct Listener: BnCameraRecordingProxyListener {
    int calls=0;
    void dataCallbackTimestamp(nsecs_t,int32_t,const sp<IMemory>&) override { ++calls; }
    void recordingFrameHandleCallbackTimestamp(nsecs_t,native_handle_t*) override { ++calls; }
    void recordingFrameHandleCallbackTimestampBatch(const std::vector<nsecs_t>&,
                                                     const std::vector<native_handle_t*>&) override { ++calls; }
    void postDataTimestamp(nsecs_t,int32_t,const sp<IMemory>&) { ++calls; }
    void postRecordingFrameHandleTimestamp(nsecs_t,native_handle_t*) { ++calls; }
    void postRecordingFrameHandleTimestampBatch(const std::vector<nsecs_t>&,
                                                 const std::vector<native_handle_t*>&) { ++calls; }
};
using CameraListener = Listener;
struct Camera {
    Mutex mLock;
    sp<android::hardware::ICamera> mCamera;
    sp<ICameraRecordingProxyListener> mRecordingProxyListener;
    bool mRecordingProxyStopped=false;
    sp<Listener> mListener;
    void stopRecording();
    status_t startRecording();
    void setRecordingProxyListener(const sp<ICameraRecordingProxyListener>&);
    void dataCallbackTimestamp(nsecs_t,int32_t,const sp<IMemory>&);
    void recordingFrameHandleCallbackTimestamp(nsecs_t,native_handle_t*);
    void recordingFrameHandleCallbackTimestampBatch(const std::vector<nsecs_t>&,
                                                    const std::vector<native_handle_t*>&);
    void releaseRecordingFrame(const sp<IMemory>& value) { if(mCamera) mCamera->releaseRecordingFrame(value); }
    void releaseRecordingFrameHandle(native_handle_t*);
    void releaseRecordingFrameHandleBatch(const std::vector<native_handle_t*>);
    struct RecordingProxy {
        sp<Camera> mCamera;
        explicit RecordingProxy(const sp<Camera>& camera):mCamera(camera) {}
        void releaseRecordingFrameHandle(native_handle_t*);
        void releaseRecordingFrameHandleBatch(const std::vector<native_handle_t*>&);
    };
};
struct IBinder {};
struct ANativeWindow {};
static std::vector<int> events;
static int connectStatus;
int native_window_api_connect(ANativeWindow*,int) { events.push_back(1); return connectStatus; }
struct PreviewHardware {
    bool enabled=true;
    int status=0, scalingCalls=0, transformCalls=0, windowCalls=0;
    sp<ANativeWindow> window;
    bool previewEnabled() { return enabled; }
    void setPreviewScalingMode(int) { ++scalingCalls; }
    void setPreviewTransform(int) { ++transformCalls; }
    int setPreviewWindow(const sp<ANativeWindow>& target) {
        ++windowCalls; events.push_back(2);
        if(status==0) window=target;
        return status;
    }
};
struct CameraClient {
    Mutex mLock;
    int mOrientation=0;
    sp<PreviewHardware> mHardware = new PreviewHardware;
    sp<IBinder> mSurface;
    sp<ANativeWindow> mPreviewWindow;
    int checkPidAndHardware() { return NO_ERROR; }
    void disconnectWindow(const sp<ANativeWindow>& window) { if(window) events.push_back(3); }
    status_t setPreviewWindow(const sp<IBinder>&,const sp<ANativeWindow>&);
};
"""

RECORDING = r"""
int main() {
    Camera camera;
    sp<android::hardware::ICamera> endpoint=new android::hardware::ICamera;
    sp<Listener> recorder=new Listener, application=new Listener;
    camera.mCamera=endpoint;
    camera.mRecordingProxyListener=std::static_pointer_cast<ICameraRecordingProxyListener>(recorder);
    camera.mListener=application;
    sp<IMemory> memory=new IMemory;
    endpoint->duringStop=[&] { camera.dataCallbackTimestamp(1,2,memory); };
    camera.stopRecording();
    assert(endpoint->stops==1 && endpoint->memories==1);
    assert(recorder->calls==0 && application->calls==0);
    camera.dataCallbackTimestamp(3,2,memory);
    assert(endpoint->memories==2 && application->calls==0);
    int peer, descriptor;
    auto* handle=makeHandle(&peer,&descriptor);
    camera.recordingFrameHandleCallbackTimestamp(3,handle);
    assert(endpoint->handles==1 && fcntl(descriptor,F_GETFD)==-1 && errno==EBADF);
    assert(close(peer)==0);
    handle=makeHandle(&peer,&descriptor);
    camera.recordingFrameHandleCallbackTimestampBatch({4},{handle});
    assert(endpoint->batches==1 && endpoint->handles==2);
    assert(fcntl(descriptor,F_GETFD)==-1 && close(peer)==0);
    endpoint->duringStop=nullptr;
    assert(camera.startRecording()==0 && endpoint->starts==1);
    camera.dataCallbackTimestamp(5,2,memory);
    assert(application->calls==1 && recorder->calls==0);
    camera.setRecordingProxyListener(std::static_pointer_cast<ICameraRecordingProxyListener>(recorder));
    assert(camera.startRecording()==0 && endpoint->starts==2);
    camera.dataCallbackTimestamp(6,2,memory);
    assert(recorder->calls==1 && application->calls==1);
    camera.stopRecording();
    std::weak_ptr<android::hardware::ICamera> lifetime=endpoint;
    camera.mCamera.clear(); endpoint.clear();
    assert(lifetime.expired());
    handle=makeHandle(&peer,&descriptor);
    camera.recordingFrameHandleCallbackTimestamp(5,handle);
    assert(fcntl(descriptor,F_GETFD)==-1 && close(peer)==0);
    handle=makeHandle(&peer,&descriptor);
    camera.recordingFrameHandleCallbackTimestampBatch({6},{handle});
    assert(fcntl(descriptor,F_GETFD)==-1 && close(peer)==0);
    assert(closedHandles==4 && deletedHandles==4);
    camera.dataCallbackTimestamp(7,2,memory);
    assert(application->calls==1);
    camera.setRecordingProxyListener(nullptr);
    camera.stopRecording();
    camera.dataCallbackTimestamp(9,2,memory);
    assert(application->calls==2);
}
"""

PREVIEW = r"""
int main() {
    for(int scenario=0;scenario<4;scenario++) {
        CameraClient client;
        client.mSurface=new IBinder;
        client.mPreviewWindow=new ANativeWindow;
        client.mHardware->window=client.mPreviewWindow;
        auto oldSurface=client.mSurface;
        auto oldWindow=client.mPreviewWindow;
        events.clear();
        if(scenario==1) client.mHardware->status=-5;
        if(scenario==2) client.mHardware->enabled=false;
        sp<IBinder> binder;
        sp<ANativeWindow> window;
        if(scenario==3) { binder=new IBinder; window=new ANativeWindow; }
        int result=client.setPreviewWindow(binder,window);
        if(scenario==1) {
            assert(result==-5 && client.mSurface==oldSurface && client.mPreviewWindow==oldWindow);
            assert(client.mHardware->window==oldWindow && events==std::vector<int>{2});
        } else {
            assert(result==0 && client.mSurface==binder && client.mPreviewWindow==window);
            if(scenario!=2) assert(client.mHardware->window==window);
            assert(events==(scenario==0 ? std::vector<int>{2,3} :
                            scenario==2 ? std::vector<int>{3} : std::vector<int>{1,2,3}));
        }
        assert(client.mHardware->scalingCalls==(scenario==3 ? 1 : 0));
        assert(client.mHardware->transformCalls==(scenario==3 ? 1 : 0));
    }
}
"""


class CameraClientReviewTest(unittest.TestCase):
    def compile_case(self, name, code):
        output = Path(os.environ["TEST_OUTPUT_DIR"]).resolve(strict=True)
        source = output / (name + ".cpp")
        binary = output / name
        source.write_text(PREFIX + code)
        subprocess.run(
            [
                os.environ.get("CXX", "c++"),
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-fsanitize=undefined",
                "-fno-sanitize-recover=all",
                str(source),
                "-o",
                str(binary),
            ],
            check=True,
        )
        subprocess.run([str(binary)], check=True)

    def test_late_recording_callbacks_release_owned_frames(self):
        source = (SOURCE / "camera/Camera.cpp").read_text()
        candidate = (CHECKOUT / "camera/Camera.cpp").read_text()
        methods = body(candidate, "class RecordingFrameReleaser") + ";\n"
        for signature in (
            "void Camera::stopRecording()",
            "status_t Camera::startRecording()",
            "void Camera::setRecordingProxyListener(",
            "void Camera::dataCallbackTimestamp(",
            "void Camera::recordingFrameHandleCallbackTimestamp(",
            "void Camera::recordingFrameHandleCallbackTimestampBatch(",
            "void Camera::releaseRecordingFrameHandle(",
            "void Camera::releaseRecordingFrameHandleBatch(",
        ):
            methods += body(source, signature) + "\n"
        self.compile_case("recording-stop", methods + RECORDING)

    def test_recording_returns_consume_handles_after_disconnect(self):
        source = (SOURCE / "camera/Camera.cpp").read_text()
        methods = "\n".join(
            body(source, signature)
            for signature in (
                "void Camera::releaseRecordingFrameHandle(",
                "void Camera::releaseRecordingFrameHandleBatch(",
                "void Camera::RecordingProxy::releaseRecordingFrameHandle(",
                "void Camera::RecordingProxy::releaseRecordingFrameHandleBatch(",
            )
        )
        self.compile_case(
            "recording-return",
            methods
            + r"""
int main() {
    for (bool proxyReturn : {false,true}) {
        for (bool connected : {false,true}) {
            sp<Camera> camera=new Camera;
            sp<android::hardware::ICamera> endpoint=new android::hardware::ICamera;
            camera->mCamera=endpoint;
            Camera::RecordingProxy proxy(camera);
            int peer,descriptor;
            auto* handle=makeHandle(&peer,&descriptor);
            // A frame reaches the client before the camera endpoint disconnects.
            if (!connected) camera->mCamera.clear();
            int closedBefore=closedHandles, deletedBefore=deletedHandles;
            if (proxyReturn) proxy.releaseRecordingFrameHandle(handle);
            else camera->releaseRecordingFrameHandle(handle);
            assert(fcntl(descriptor,F_GETFD)==-1 && errno==EBADF);
            assert(close(peer)==0);
            assert(closedHandles==closedBefore+1 && deletedHandles==deletedBefore+1);
            assert(endpoint->handles==(connected?1:0));
            std::vector<native_handle_t*> handles;
            std::vector<int> peers,descriptors;
            for (int index=0;index<2;++index) {
                handles.push_back(makeHandle(&peer,&descriptor));
                peers.push_back(peer); descriptors.push_back(descriptor);
            }
            closedBefore=closedHandles; deletedBefore=deletedHandles;
            if (proxyReturn) proxy.releaseRecordingFrameHandleBatch(handles);
            else camera->releaseRecordingFrameHandleBatch(handles);
            for (int value:descriptors) assert(fcntl(value,F_GETFD)==-1 && errno==EBADF);
            for (int value:peers) assert(close(value)==0);
            assert(closedHandles==closedBefore+2 && deletedHandles==deletedBefore+2);
            assert(endpoint->batches==(connected?1:0));
            assert(endpoint->handles==(connected?3:0));
            camera->mCamera.clear();
            closedBefore=closedHandles; deletedBefore=deletedHandles;
            proxy.releaseRecordingFrameHandle(nullptr);
            camera->releaseRecordingFrameHandle(nullptr);
            proxy.releaseRecordingFrameHandleBatch({nullptr});
            camera->releaseRecordingFrameHandleBatch({});
            assert(closedHandles==closedBefore && deletedHandles==deletedBefore);
        }
    }
}
""",
        )

    def test_only_documented_hal_sentinel_selects_default(self):
        source = (
            SOURCE / "services/camera/libcameraservice/CameraService.cpp"
        ).read_text()
        method = body(source, "Status CameraService::makeClient(")
        condition = re.search(r"if \(([^)]*)\)", method).group(1)
        self.compile_case(
            "hal-version",
            """
constexpr int CAMERA_HAL_API_VERSION_UNSPECIFIED=-1;
static bool defaultVersion(int halVersion, int deviceVersion) { return """
            + condition
            + """; }
int main() {
    assert(defaultVersion(-1,256));
    assert(defaultVersion(256,256));
    assert(!defaultVersion(-2,256));
    assert(!defaultVersion(INT32_MIN,256));
    assert(!defaultVersion(0,256));
}
""",
        )

    def test_preview_removal_reaches_hal_before_disconnect(self):
        source = (
            SOURCE / "services/camera/libcameraservice/api1/CameraClient.cpp"
        ).read_text()
        self.compile_case(
            "preview-target",
            body(source, "status_t CameraClient::setPreviewWindow(") + PREVIEW,
        )


if __name__ == "__main__":
    unittest.main()
