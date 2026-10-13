"""Exercise HAL1 recording, callback, dump and device-removal production bodies.

TEST_OUTPUT_DIR names an existing retained host build directory.
"""

import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(
    os.environ.get("CAMERA_SERVICE_SOURCE", Path(__file__).resolve().parents[1])
)


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
#include <algorithm>
#include <cstdint>
#include <functional>
#include <fcntl.h>
#include <unistd.h>
#include <cerrno>
#include <cstdio>
#include <memory>
#include <mutex>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>
#include <sys/types.h>
#define ALOGE(...) ((void)0)
#define ALOGV(...) ((void)0)
#define CC_LIKELY(value) (value)
using status_t = int;
using nsecs_t = int64_t;
constexpr int OK = 0, NO_MEMORY = -12, DEAD_OBJECT = -32;
struct String16 {};
template<class T> using Vector = std::vector<T>;
template<class T> struct sp {
    T* value = nullptr;
    sp() = default;
    sp(T* pointer): value(pointer) {}
    T* operator->() const { return value; }
    bool operator==(std::nullptr_t) const { return value == nullptr; }
    bool operator!=(std::nullptr_t) const { return value != nullptr; }
};
struct native_handle_t { int data[1]; };
static bool allocationFails;
static int allocations, deletions, dumpCalls, callbacks, failures;
native_handle_t* native_handle_create(int, int) {
    if (allocationFails) return nullptr;
    ++allocations;
    return new native_handle_t;
}
int native_handle_close(native_handle_t* handle) { return close(handle->data[0]); }
int native_handle_delete(native_handle_t* handle) { ++deletions; delete handle; return 0; }
using Status = int;
namespace hardware {
template<class T> struct Return {
    T value; bool okay=true;
    Return(T data,bool success=true):value(data),okay(success) {}
    bool isOk() const { return okay; }
    operator T() const { return value; }
};
template<> struct Return<void> {};
Return<void> Void() { return {}; }
}
struct VideoFrameMessage;
static std::function<void(const std::vector<VideoFrameMessage>&)> releaseBatchHook;
static bool dumpTransportOk=true;
struct Device {
    void releaseRecordingFrameHandleBatch(const std::vector<VideoFrameMessage>& messages) {
        if (releaseBatchHook) releaseBatchHook(messages);
    }
    hardware::Return<Status> dumpState(native_handle_t* handle) {
        ++dumpCalls; return {handle->data[0],dumpTransportOk};
    }
};
struct IMemoryHeap {
    int id = 7;
    size_t bytes = 128;
    int getHeapID() { return id; }
    size_t getSize() { return bytes; }
};
constexpr int kMetadataBufferTypeNativeHandleSource=3;
struct VideoNativeHandleMetadata { int eType; native_handle_t* pHandle; };
static std::function<void()> beforeGetMemory;
struct IMemory {
    IMemoryHeap* heap = nullptr;
    ssize_t offset = 0;
    size_t bytes = 32;
    VideoNativeHandleMetadata metadata = {};
    sp<IMemoryHeap> getMemory(ssize_t* resultOffset, size_t* resultSize) {
        if (beforeGetMemory) { auto hook=beforeGetMemory; beforeGetMemory=nullptr; hook(); }
        *resultOffset = offset; *resultSize = bytes; return heap;
    }
    size_t size() const { return bytes; }
    void* unsecurePointer() { return &metadata; }
};
struct camera_memory_t { void* handle; };
struct camera_frame_metadata_t {};

using DataCallbackMsg = int;
struct hidl_handle {
    native_handle_t* handle;
    hidl_handle(native_handle_t* value=nullptr):handle(value) {}
    native_handle_t* getNativeHandle() const { return handle; }
};
struct VideoFrameMessage { hidl_handle frameData; uint32_t data; uint32_t bufferIndex; };
namespace android { struct HandleTimestampMessage { int64_t timestamp; sp<IMemory> dataPtr; }; }
namespace hardware {
template<class T> using hidl_vec=std::vector<T>;
namespace camera::device::V1_0 {
struct HandleTimestampMessage { hidl_handle frameData; uint32_t data; uint32_t bufferIndex; int64_t timestamp; };
}
}
struct CameraProviderManager;
static int initializeResult, retainedReferences, releases, windowResult, surfaceResult;
struct String8 {
    std::string value;
    String8(const char* text = "0"): value(text) {}
    const char* string() const { return value.c_str(); }
};
struct Parameters {};
struct CameraHardwareInterface {
    static std::vector<CameraHardwareInterface*> allocated;
    static void* operator new(size_t bytes) {
        auto* result=static_cast<CameraHardwareInterface*>(::operator new(bytes));
        allocated.push_back(result);
        return result;
    }
    static void operator delete(void* pointer) { ::operator delete(pointer); }
    CameraHardwareInterface(const char* = "0") {}
    int initialize(sp<CameraProviderManager>) { ++retainedReferences; return initializeResult; }
    void release() { ++releases; }
    void setCallbacks(void*,void*,void*,void*,void*) {}
    Parameters getParameters() { return {}; }
    struct CameraHeapMemory {
        size_t mBufSize = 32;
        unsigned mNumBufs = 2;
        sp<IMemory> mBuffers[2];
        camera_memory_t handle{this};
    };
    std::unordered_map<int, camera_memory_t*> mHidlMemPoolMap;
    std::mutex mHidlMemPoolMapLock;
    sp<Device> mHidlDevice;
    void* mCbUser = nullptr;
    void (*mDataCbTimestampBatch)(int32_t,const std::vector<android::HandleTimestampMessage>&,void*)=nullptr;
    void releaseRecordingFrameBatch(const std::vector<sp<IMemory>>&);
    hardware::Return<void> handleCallbackTimestampBatch(DataCallbackMsg,const hardware::hidl_vec<hardware::camera::device::V1_0::HandleTimestampMessage>&);
    void (*mNotifyCb)(int32_t,int32_t,int32_t,void*) = nullptr;
    void (*mDataCb)(int32_t,sp<IMemory>,camera_frame_metadata_t*,void*) = nullptr;
    void (*mDataCbTimestamp)(nsecs_t,int32_t,sp<IMemory>,void*) = nullptr;
    bool getRecordingFrameSlot(const sp<IMemory>&,uint32_t*,uint32_t*);
    status_t dump(int,const Vector<String16>&) const;
    static void sNotifyCb(int32_t,int32_t,int32_t,void*);
    static void sDataCb(int32_t,const camera_memory_t*,unsigned,camera_frame_metadata_t*,void*);
    static void sDataCbTimestamp(nsecs_t,int32_t,const camera_memory_t*,unsigned,void*);
    hardware::Return<void> handleCallbackTimestamp(DataCallbackMsg,const hidl_handle&,uint32_t,uint32_t,int64_t);
};
std::vector<CameraHardwareInterface*> CameraHardwareInterface::allocated;
struct CameraProviderManager {
    enum class DeviceMode { CAMERA };
    void removeRef(DeviceMode,const char*) { --retainedReferences; }
    static int mapToStatusT(int result) { return result; }
    struct ProviderInfo {
        struct DeviceInfo {
            std::string mId;
            bool compatible;
            bool isAPI1Compatible() { return compatible; }
        };
        std::vector<std::unique_ptr<DeviceInfo>> mDevices;
        std::set<std::string> mUniqueCameraIds;
        std::vector<std::string> mUniqueAPI1CompatibleCameraIds;
        void removeDevice(std::string);
    };
};
struct CameraHardwareInterfaceFlashControl {
    sp<CameraProviderManager> mProviderManager;
    Parameters mParameters;
    String8 mCameraId;
    sp<CameraHardwareInterface> mDevice;
    int getSmallestSurfaceSize(int32_t* width,int32_t* height) { *width=1; *height=1; return surfaceResult; }
    int initializePreviewWindow(sp<CameraHardwareInterface>,int32_t,int32_t) { return windowResult; }
    status_t connectCameraDevice(const String8&);
    void releaseDevice(const sp<CameraHardwareInterface>&,const String8&);
};
static void check(bool passed, const char* name) {
    if (!passed) { ++failures; std::fprintf(stderr,"FAIL: %s\n",name); }
}
"""

CASES = r"""
int main() {
    CameraHardwareInterface camera;
    IMemoryHeap heap;
    IMemory memory{&heap,32,32,{}}, other{&heap,0,32,{}};
    CameraHardwareInterface::CameraHeapMemory pool{32,2,{&other,&memory}};
    camera_memory_t registered{&pool};
    camera.mHidlMemPoolMap[7] = &registered;
    uint32_t id = 99, slot = 99;
    check(camera.getRecordingFrameSlot(&memory,&id,&slot) && id==7 && slot==1,"registered slot");
    check(!camera.getRecordingFrameSlot(nullptr,&id,&slot),"null release");
    for (int scenario=0; scenario<7; ++scenario) {
        IMemory malformed = memory;
        IMemoryHeap foreign = heap;
        switch (scenario) {
            case 0: malformed.heap=nullptr; break;
            case 1: malformed.offset=-1; break;
            case 2: malformed.offset=3; break;
            case 3: malformed.bytes=16; malformed.offset=16; break;
            case 4: malformed.offset=64; break;
            case 5: foreign.id=8; malformed.heap=&foreign; break;
            case 6: malformed.bytes=0; break;
        }
        check(!camera.getRecordingFrameSlot(&malformed,&id,&slot),"reject forged slot");
    }
    camera.sNotifyCb(1,2,3,&camera);
    camera.sDataCb(1,&registered,0,nullptr,&camera);
    camera.sDataCbTimestamp(1,2,&registered,0,&camera);
    camera.mNotifyCb = [](int32_t,int32_t,int32_t,void*) { ++callbacks; };
    camera.mDataCb = [](int32_t,sp<IMemory>,camera_frame_metadata_t*,void*) { ++callbacks; };
    camera.mDataCbTimestamp = [](nsecs_t,int32_t,sp<IMemory>,void*) { ++callbacks; };
    camera.sNotifyCb(1,2,3,&camera);
    camera.sDataCb(1,&registered,0,nullptr,&camera);
    camera.sDataCbTimestamp(1,2,&registered,0,&camera);
    check(callbacks==3,"enabled callbacks");
    camera.sDataCb(1,&registered,2,nullptr,&camera);
    camera.sDataCbTimestamp(1,2,&registered,2,&camera);
    check(callbacks==3,"invalid callback indices");
    native_handle_t frame;
    camera.handleCallbackTimestamp(1,{&frame},7,2,1);
    check(callbacks==3,"invalid handle index");
    pool.mBufSize=1;
    camera.handleCallbackTimestamp(1,{&frame},7,0,1);
    check(callbacks==3,"undersized handle metadata");
    pool.mBufSize=32;
    camera.handleCallbackTimestamp(1,{&frame},7,0,1);
    check(callbacks==4 && other.metadata.pHandle==&frame &&
          other.metadata.eType==kMetadataBufferTypeNativeHandleSource,"valid handle metadata type");
    camera.mDataCbTimestampBatch=[](int32_t,const std::vector<android::HandleTimestampMessage>& messages,void*) {
        ++callbacks;
        check(messages.size()==2,"batch callback count");
        for (const auto& message:messages) {
            auto* metadata=static_cast<VideoNativeHandleMetadata*>(message.dataPtr->unsecurePointer());
            check(metadata->eType==kMetadataBufferTypeNativeHandleSource && metadata->pHandle!=nullptr,
                  "batch metadata type");
        }
    };
    other.metadata.eType=-1; memory.metadata.eType=-1;
    camera.handleCallbackTimestampBatch(1,{{&frame,7,0,1},{&frame,7,1,2}});
    check(callbacks==5,"valid batch callback");
    camera.handleCallbackTimestampBatch(1,{{&frame,7,2,1}});
    camera.handleCallbackTimestampBatch(1,{{&frame,8,0,1}});
    pool.mBufSize=1;
    camera.handleCallbackTimestampBatch(1,{{&frame,7,0,1}});
    pool.mBufSize=32;
    check(callbacks==5,"invalid batch rejected");
    camera.mDataCbTimestampBatch=nullptr;
    camera.handleCallbackTimestampBatch(1,{{&frame,7,0,1}});
    check(callbacks==5,"absent batch callback");
    Device device;
    camera.mHidlDevice=&device;
    for (int scenario=0; scenario<6; ++scenario) {
        IMemory first{&heap,0,sizeof(VideoNativeHandleMetadata),{}};
        IMemory second{&heap,static_cast<ssize_t>(sizeof(VideoNativeHandleMetadata)),sizeof(VideoNativeHandleMetadata),{}};
        pool.mBufSize=sizeof(VideoNativeHandleMetadata);
        camera.mHidlMemPoolMap[7]=&registered;
        camera.mHidlDevice=&device;
        int descriptors[2]={open("/dev/null",O_RDONLY),open("/dev/null",O_RDONLY)};
        native_handle_t* originals[2]={native_handle_create(1,0),native_handle_create(1,0)};
        for (int index=0; index<2; ++index) {
            check(descriptors[index]>=0,"open batch descriptor");
            originals[index]->data[0]=descriptors[index];
        }
        first.metadata={kMetadataBufferTypeNativeHandleSource,originals[0]};
        second.metadata={kMetadataBufferTypeNativeHandleSource,originals[1]};
        int expected=scenario==0 ? 2 : scenario==1 || scenario==4 || scenario==5 ? 1 : 0;
        if (scenario==1) second.offset=3;
        if (scenario==2) beforeGetMemory=[&]() { camera.mHidlMemPoolMap.clear(); };
        if (scenario==3) camera.mHidlDevice=nullptr;
        if (scenario==4) second.offset=2*sizeof(VideoNativeHandleMetadata);
        IMemory malformed{&heap,0,1,{}};
        bool called=false;
        releaseBatchHook=[&](const std::vector<VideoFrameMessage>& messages) {
            called=true;
            check(static_cast<int>(messages.size())==expected,"batch forwards valid slots");
            for (const auto& message:messages) {
                auto* handle=message.frameData.getNativeHandle();
                check(fcntl(handle->data[0],F_GETFD)!=-1,"forwarded original stays open");
            }
            // A passthrough HAL can replace shared metadata with its own clone.
            first.metadata.pHandle=nullptr; second.metadata.pHandle=nullptr;
        };
        int deletedBefore=deletions;
        if (scenario==5) {
            native_handle_close(originals[1]); native_handle_delete(originals[1]);
            camera.releaseRecordingFrameBatch({&first,&malformed,nullptr});
        } else {
            camera.releaseRecordingFrameBatch({&first,&second});
        }
        check(expected==0 || called,"valid batch reaches HAL");
        check(deletions==deletedBefore+2,"every incoming handle deleted exactly once");
        for (int descriptor:descriptors) {
            errno=0;
            check(fcntl(descriptor,F_GETFD)==-1 && errno==EBADF,"every incoming descriptor closes");
        }
    }
    releaseBatchHook=nullptr;
    camera.mHidlDevice=&device;
    allocationFails=true;
    check(camera.dump(11,{})==NO_MEMORY && dumpCalls==0,"dump allocation failure");
    allocationFails=false;
    check(camera.dump(11,{})==11 && dumpCalls==1 && allocations==deletions,"dump ownership");
    dumpTransportOk=false;
    check(camera.dump(11,{})==DEAD_OBJECT && allocations==deletions,"dump transport cleanup");
    CameraProviderManager::ProviderInfo provider;
    for (const char* value : {"0","0","1"}) {
        provider.mDevices.push_back(std::make_unique<CameraProviderManager::ProviderInfo::DeviceInfo>(
                CameraProviderManager::ProviderInfo::DeviceInfo{value,true}));
        provider.mUniqueCameraIds.insert(value);
    }
    provider.mUniqueAPI1CompatibleCameraIds={"0","1"};
    provider.removeDevice("0");
    check(provider.mDevices.size()==1 && provider.mDevices[0]->mId=="1","all interface versions removed");
    check(provider.mUniqueCameraIds==std::set<std::string>{"1"} &&
          provider.mUniqueAPI1CompatibleCameraIds==std::vector<std::string>{"1"},"logical ID lists");
    provider.removeDevice("0");
    check(provider.mDevices.size()==1,"repeat removal");
    CameraProviderManager manager;
    CameraHardwareInterfaceFlashControl torch;
    torch.mProviderManager=&manager;
    initializeResult=-5;
    check(torch.connectCameraDevice(String8("0"))==-5 && retainedReferences==0 && releases==1,
          "failed torch open drops provider reference");
    initializeResult=0; surfaceResult=-6;
    check(torch.connectCameraDevice(String8("0"))==-6 && retainedReferences==0 && releases==2,
          "failed torch surface drops provider reference");
    surfaceResult=0; windowResult=-7;
    check(torch.connectCameraDevice(String8("0"))==-7 && retainedReferences==0 && releases==3,
          "failed torch window drops provider reference");
    windowResult=0;
    check(torch.connectCameraDevice(String8("0"))==0 && retainedReferences==1,
          "successful torch retains provider reference");
    torch.releaseDevice(torch.mDevice,String8("0"));
    check(retainedReferences==0 && releases==4,"torch close drops provider reference");
    for (auto* allocated : CameraHardwareInterface::allocated) delete allocated;
    return failures ? 1 : 0;
}
"""


class Hal1ReviewBoundaries(unittest.TestCase):
    def test_production_functions(self):
        source = (ROOT / "device1/CameraHardwareInterface.cpp").read_text()
        manager = (ROOT / "common/CameraProviderManager.cpp").read_text()
        signatures = (
            "bool CameraHardwareInterface::getRecordingFrameSlot(",
            "status_t CameraHardwareInterface::dump(",
            "void CameraHardwareInterface::sNotifyCb(",
            "void CameraHardwareInterface::sDataCb(",
            "void CameraHardwareInterface::sDataCbTimestamp(",
            "hardware::Return<void> CameraHardwareInterface::handleCallbackTimestamp(",
            "hardware::Return<void> CameraHardwareInterface::handleCallbackTimestampBatch(",
            "void CameraHardwareInterface::releaseRecordingFrameBatch(",
        )
        extracted = "\n".join(function(source, signature) for signature in signatures)
        extracted += function(
            manager, "void CameraProviderManager::ProviderInfo::removeDevice("
        )
        flashlight = (ROOT / "CameraFlashlight.cpp").read_text()
        extracted += function(
            flashlight,
            "status_t CameraHardwareInterfaceFlashControl::connectCameraDevice(",
        )
        extracted += function(
            flashlight, "void CameraHardwareInterfaceFlashControl::releaseDevice("
        )
        output = Path(os.environ["TEST_OUTPUT_DIR"]).resolve(strict=True)
        fixture = output / "hal1_review_boundaries.cpp"
        executable = output / "hal1_review_boundaries"
        fixture.write_text(PREFIX + extracted + CASES)
        subprocess.run(
            [
                "clang++",
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-fsanitize=address,undefined",
                "-fno-sanitize-recover=all",
                str(fixture),
                "-o",
                str(executable),
            ],
            check=True,
        )
        subprocess.run([str(executable)], check=True)

    def test_torch_and_batch_contracts(self):
        source = (ROOT / "CameraFlashlight.cpp").read_text()
        connect = function(
            source, "status_t CameraHardwareInterfaceFlashControl::connectCameraDevice("
        )
        failure = connect[
            connect.index("if (res) {") : connect.index("// need to set __get_memory")
        ]
        self.assertLess(
            failure.index("releaseDevice(device, cameraId);"),
            failure.index("return res;"),
        )
        source = (ROOT / "device1/CameraHardwareInterface.cpp").read_text()
        batch = function(
            source,
            "hardware::Return<void> CameraHardwareInterface::handleCallbackTimestampBatch(",
        )
        self.assertIn("if (mDataCbTimestampBatch != nullptr)", batch)
        self.assertIn("mem->mBufSize < sizeof(VideoNativeHandleMetadata)", batch)
        release = function(
            source, "void CameraHardwareInterface::releaseRecordingFrameBatch("
        )
        self.assertIn("getRecordingFrameSlot(mem, &heapId, &bufferIndex)", release)


if __name__ == "__main__":
    unittest.main()
