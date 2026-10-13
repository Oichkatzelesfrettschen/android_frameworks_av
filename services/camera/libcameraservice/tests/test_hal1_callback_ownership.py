"""Inject unregistration at mutex release in the production HAL1 callbacks.

The fixture substitutes an instrumented mutex type and retains every production
statement. TEST_OUTPUT_DIR names an existing retained host build directory.
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
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <vector>
#define ALOGE(...) ((void)0)
using DataCallbackMsg=int;
using nsecs_t=int64_t;
constexpr int CAMERA_MSG_VIDEO_FRAME=32;
struct camera_memory_t { void* handle; };
struct native_handle_t {};
constexpr int kMetadataBufferTypeNativeHandleSource=3;
struct VideoNativeHandleMetadata { int eType=0; native_handle_t* pHandle=nullptr; };
struct Memory : std::enable_shared_from_this<Memory> { VideoNativeHandleMetadata metadata; void* unsecurePointer() { return &metadata; } };
using MemoryBase=Memory;
struct camera_face_t {};
struct camera_frame_metadata_t { size_t number_of_faces; camera_face_t* faces; };
namespace hardware {
    template<class T> struct Return {};
    Return<void> Void() { return {}; }
    namespace camera::device::V1_0 { struct CameraFrameMetadata { std::vector<camera_face_t> faces; }; }
}
struct hidl_handle { native_handle_t* handle=nullptr; native_handle_t* getNativeHandle() const { return handle; } };
static std::function<void()> afterUnlock;
struct BoundaryMutex {
    std::mutex inner;
    void lock() { inner.lock(); }
    void unlock() { inner.unlock(); if (afterUnlock) { auto hook=afterUnlock; afterUnlock=nullptr; hook(); } }
};
template<class T> struct sp {
    std::shared_ptr<T> pointer;
    sp()=default;
    sp(T* value):pointer(value->shared_from_this()) {}
    sp& operator=(T* value) { pointer=value->shared_from_this(); return *this; }
    T* operator->() const { return pointer.get(); }
    bool operator==(std::nullptr_t) const { return pointer==nullptr; }
};
static int destroyed, callbacks;
struct CameraHardwareInterface {
    struct CameraHeapMemory : std::enable_shared_from_this<CameraHeapMemory> {
        size_t mBufSize=sizeof(VideoNativeHandleMetadata);
        unsigned mNumBufs=1;
        std::shared_ptr<Memory> memory=std::make_shared<Memory>();
        Memory* mBuffers[1]={memory.get()};
        sp<Memory> getBuffer(uint32_t) { return memory.get(); }
        camera_memory_t handle{this};
        ~CameraHeapMemory() { ++destroyed; }
    };
    BoundaryMutex mHidlMemPoolMapLock;
    std::unordered_map<int,camera_memory_t*> mHidlMemPoolMap;
    static std::shared_ptr<CameraHeapMemory> registrationOwner;
    void* mCbUser=nullptr;
    void (*mDataCbTimestamp)(nsecs_t,int32_t,const sp<Memory>&,void*)=nullptr;
    hardware::Return<void> unregisterMemory(uint32_t);
    hardware::Return<void> dataCallback(DataCallbackMsg,uint32_t,uint32_t,
        const hardware::camera::device::V1_0::CameraFrameMetadata&);
    hardware::Return<void> dataCallbackTimestamp(DataCallbackMsg,uint32_t,uint32_t,int64_t);
    hardware::Return<void> handleCallbackTimestamp(DataCallbackMsg,const hidl_handle&,uint32_t,uint32_t,int64_t);
    void releaseUndeliveredRecordingFrame(uint32_t,uint32_t,const hidl_handle&) {}
    static void sPutMemory(camera_memory_t*) { registrationOwner.reset(); }
    static void sDataCb(int32_t,const camera_memory_t* memory,unsigned,camera_frame_metadata_t*,void*) {
        auto* heap=static_cast<CameraHeapMemory*>(memory->handle);
        if (heap->mNumBufs==1 && destroyed==0) ++callbacks;
    }
    static void sDataCbTimestamp(nsecs_t,int32_t,const camera_memory_t* memory,unsigned,void*) {
        auto* heap=static_cast<CameraHeapMemory*>(memory->handle);
        if (heap->mNumBufs==1 && destroyed==0) ++callbacks;
    }
};
std::shared_ptr<CameraHardwareInterface::CameraHeapMemory> CameraHardwareInterface::registrationOwner;
"""
CASES = r"""
int main() {
    for (int variant=0; variant<3; ++variant) {
        CameraHardwareInterface camera;
        destroyed=0; callbacks=0;
        camera.registrationOwner=std::make_shared<CameraHardwareInterface::CameraHeapMemory>();
        camera.mHidlMemPoolMap[7]=&camera.registrationOwner->handle;
        bool retainedAtUnlock=false;
        afterUnlock=[&]() {
            camera.unregisterMemory(7);
            retainedAtUnlock=destroyed==0;
        };
        if (variant==0) camera.dataCallback(1,7,0,{});
        if (variant==1) camera.dataCallbackTimestamp(1,7,0,1);
        native_handle_t frame;
        camera.mDataCbTimestamp=[](nsecs_t,int32_t,const sp<Memory>&,void*) { if (destroyed==0) ++callbacks; };
        if (variant==2) camera.handleCallbackTimestamp(1,{&frame},7,0,1);
        if (!retainedAtUnlock || callbacks!=1 || destroyed!=1 || !camera.mHidlMemPoolMap.empty()) return 1;
    }
    return 0;
}
"""


class CallbackOwnership(unittest.TestCase):
    def test_unregister_between_lookup_and_dispatch(self):
        source = (ROOT / "device1/CameraHardwareInterface.cpp").read_text()
        methods = "\n".join(
            function(
                source, "hardware::Return<void> CameraHardwareInterface::" + name + "("
            )
            for name in [
                "unregisterMemory",
                "dataCallback",
                "dataCallbackTimestamp",
                "handleCallbackTimestamp",
            ]
        )
        methods = methods.replace(
            "std::lock_guard<std::mutex>", "std::lock_guard<BoundaryMutex>"
        )
        output = Path(os.environ["TEST_OUTPUT_DIR"]).resolve(strict=True)
        fixture = output / "hal1_callback_ownership.cpp"
        fixture.write_text(PREFIX + methods + CASES)
        binary = output / "hal1_callback_ownership"
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
                str(binary),
            ],
            check=True,
        )
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
