"""Exercise retained listener capability through provider removal and rediscovery."""

import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(os.environ.get("CAMERA_SERVICE_SOURCE", Path(__file__).resolve().parents[1]))


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    position = opening + 1
    while depth:
        depth += (source[position] == "{") - (source[position] == "}")
        position += 1
    return source[start:position]


PREFIX = r"""
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <string>
#include <vector>
#define ALOGE(...) ((void)0)
#define ALOGW(...) ((void)0)
#define ALOGV(...) ((void)0)
using status_t=int;
constexpr int OK=0, NAME_NOT_FOUND=-2;
struct String8 : std::string {
    using std::string::string;
    const char* string() const { return c_str(); }
};
using String16=String8;
struct Mutex {
    mutable std::mutex mutex;
    struct Autolock { std::lock_guard<std::mutex> lock; explicit Autolock(const Mutex& value):lock(value.mutex) {} };
};
struct CameraParameters {};
enum class SystemCameraKind { PUBLIC };
enum class TorchModeStatus { AVAILABLE_OFF, NOT_AVAILABLE };
namespace binder { struct Status { bool ok; bool isOk() const { return ok; } }; }
namespace hardware {
struct ICameraService { static constexpr int API_VERSION_2=2; };
namespace camera::common::V1_0 {
struct CameraResourceCost { int resourceCost=10; std::vector<std::string> conflictingDevices; };
}
}
struct Provider {
    bool present=true, api2=true;
    int queries=0;
    status_t getResourceCost(const std::string&,hardware::camera::common::V1_0::CameraResourceCost*) { return OK; }
    status_t getSystemCameraKind(const std::string&,SystemCameraKind*) { return OK; }
};
struct Flashlight { bool hasFlashUnit(const String8&) { return false; } };
struct TorchMap { void add(const String8&,TorchModeStatus) {} };
struct Listener {
    bool vendor;
    std::vector<int> statuses;
    bool isVendorListener() const { return vendor; }
    int getListenerPid() const { return 1; }
    int getListenerUid() const { return 1; }
    Listener* getListener() { return this; }
    void onStatusChanged(int status,const String16&) { statuses.push_back(status); }
};
struct CameraService {
    enum class StatusInternal { NOT_PRESENT, PRESENT, ENUMERATING, NOT_AVAILABLE };
"""

SERVICE = r"""
    Provider* mCameraProviderManager;
    Flashlight* mFlashlight;
    Mutex mCameraStatesLock,mTorchStatusMutex,mStatusListenerLock;
    TorchMap mTorchStatusMap;
    std::map<String8,std::shared_ptr<CameraState>> mCameraStates;
    std::vector<std::shared_ptr<Listener>> mListenerList;
    std::shared_ptr<CameraState> getCameraState(const String8& id) {
        auto found=mCameraStates.find(id);
        return found==mCameraStates.end() ? nullptr : found->second;
    }
    binder::Status supportsCameraApi(const String16&,int,bool* supports) {
        ++mCameraProviderManager->queries;
        if (!mCameraProviderManager->present) return {false};
        *supports=mCameraProviderManager->api2;
        return {true};
    }
    status_t getSystemCameraKind(const String8& id,SystemCameraKind* kind) {
        auto state=getCameraState(id);
        if (!state) return NAME_NOT_FOUND;
        *kind=state->getSystemCameraKind(); return OK;
    }
    void broadcastTorchModeStatus(const String8&,TorchModeStatus,SystemCameraKind) {}
    void updateCameraNumAndIds() {}
    void logDeviceAdded(const String8&,const char*) {}
    std::vector<String16> getLogicalCameras(const String8&) { return {}; }
    status_t getTorchStatusLocked(const String8&,TorchModeStatus*) { return NAME_NOT_FOUND; }
    void onTorchStatusChangedLocked(const String8&,TorchModeStatus,SystemCameraKind) {}
    static int mapToInterface(StatusInternal status) { return static_cast<int>(status); }
    void notifyPhysicalCameraStatusLocked(int,const String16&,const std::vector<String16>&,SystemCameraKind) {}
    static bool shouldSkipStatusUpdates(SystemCameraKind,bool,int,int) { return false; }
    void addStates(String8);
    void updateStatus(StatusInternal,const String8&,std::initializer_list<StatusInternal>);
};
static int failures=0;
static void check(bool condition,const char* message) {
    if (!condition) { ++failures; std::fprintf(stderr,"FAIL: %s\n",message); }
}
"""

CASES = r"""
int main() {
    for (bool api2 : {false,true}) {
        Provider provider;
        provider.api2=api2;
        Flashlight flashlight;
        CameraService service;
        service.mCameraProviderManager=&provider;
        service.mFlashlight=&flashlight;
        auto vendor=std::make_shared<Listener>(); vendor->vendor=true;
        auto framework=std::make_shared<Listener>(); framework->vendor=false;
        service.mListenerList={vendor,framework};
        service.addStates("0");
        service.updateStatus(CameraService::StatusInternal::PRESENT,"0",{});
        const int queries=provider.queries;
        provider.present=false;
        service.updateStatus(CameraService::StatusInternal::NOT_PRESENT,"0",{});
        service.updateStatus(CameraService::StatusInternal::NOT_PRESENT,"0",{});
        check(vendor->statuses==(api2 ? std::vector<int>{1,0} : std::vector<int>{}),
              "vendor availability and removal retain the same capability");
        check(framework->statuses==std::vector<int>({1,0}),"framework removal remains balanced and idempotent");
        check(provider.queries==queries,"removal uses retained state after provider deletion");
        service.mCameraStates.clear();
        provider.present=true; provider.api2=!api2;
        service.addStates("0");
        service.updateStatus(CameraService::StatusInternal::PRESENT,"0",{});
        provider.present=false;
        service.updateStatus(CameraService::StatusInternal::NOT_PRESENT,"0",{});
        check(vendor->statuses==std::vector<int>({1,0}),"rediscovery refreshes retained capability");
        check(framework->statuses==std::vector<int>({1,0,1,0}),"rediscovery delivers both framework edges");
        service.mCameraStates.clear();
        service.addStates("0");
        check(service.mCameraStates.empty(),"failed capability query admits zero camera states");
    }
    return failures==0 ? 0 : 1;
}
"""


class CameraRemovalCapabilityTest(unittest.TestCase):
    def test_provider_removal_preserves_listener_capability(self):
        source = (ROOT / "CameraService.cpp").read_text()
        header = (ROOT / "CameraService.h").read_text()
        state = function(header, "class CameraState {") + ";"
        signatures = [
            "CameraService::CameraState::CameraState(",
            "CameraService::CameraState::~CameraState()",
            "SystemCameraKind CameraService::CameraState::getSystemCameraKind() const",
            "template<class Func>\nvoid CameraService::CameraState::updateStatus(",
            "void CameraService::addStates(",
            "void CameraService::updateStatus(StatusInternal status, const String8& cameraId,",
        ]
        if "bool CameraService::CameraState::supportsHAL3() const" in source:
            signatures.append("bool CameraService::CameraState::supportsHAL3() const")
        extracted = "\n".join(function(source, signature) for signature in signatures)
        output = Path(os.environ["TEST_OUTPUT_DIR"]).resolve(strict=True)
        fixture = output / "camera_removal_capability.cpp"
        executable = output / "camera_removal_capability"
        fixture.write_text(PREFIX + state + SERVICE + extracted + CASES)
        subprocess.run(["clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                        str(fixture), "-o", str(executable)], check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
