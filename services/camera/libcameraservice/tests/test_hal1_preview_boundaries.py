"""Exercise HAL1 preview callbacks and stale buffer admission with native-window fixtures.

The fixture instruments the production mutex type to check lock ownership.
TEST_OUTPUT_DIR names an existing retained build directory.
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
#include <unordered_map>
#include <mutex>
#include <utility>
#include <cstdio>
#define ALOGE(...) ((void)0)
#define ALOGV(...) ((void)0)
#define CC_LIKELY(value) (value)
using status_t=int;
constexpr int OK=0, INVALID_OPERATION=-38, NOT_SET=-1, NATIVE_WINDOW_API_CAMERA=1, NATIVE_WINDOW_MIN_UNDEQUEUED_BUFFERS=2;
enum class Status { OK, INTERNAL_ERROR, ILLEGAL_ARGUMENT };
namespace hardware {
template<class T> struct Return { T value; Return(T data):value(data) {} operator T() const { return value; } };
template<> struct Return<void> {};
Return<void> Void() { return {}; }
}
static int failures;
static void check(bool result,const char* name) { if (!result) { ++failures; std::fprintf(stderr,"FAIL: %s\n",name); } }
static std::function<void()> afterUnlock;
struct BoundaryMutex {
    bool held=false;
    void lock() { check(!held,"mutex nonrecursive"); held=true; }
    void unlock() {
        check(held,"mutex owned"); held=false;
        if (afterUnlock) { auto hook=afterUnlock; afterUnlock=nullptr; hook(); }
    }
};
template<class T> struct sp {
    T* pointer=nullptr;
    sp()=default;
    sp(T* value):pointer(value) {}
    T* get() const { return pointer; }
    T* operator->() const { return pointer; }
    bool operator==(const sp& other) const { return pointer==other.pointer; }
    bool operator!=(std::nullptr_t) const { return pointer!=nullptr; }
};
struct native_handle_t { bool alive=true; };
using buffer_handle_t=const native_handle_t*;
struct hidl_handle {
    buffer_handle_t pointer=nullptr;
    hidl_handle(std::nullptr_t=nullptr) {}
    hidl_handle(buffer_handle_t value):pointer(value) {}
};
struct ANativeWindowBuffer { buffer_handle_t handle; uint32_t stride=8; };
struct GraphicBuffer;
template<> struct sp<GraphicBuffer> {
    GraphicBuffer* pointer=nullptr;
    sp()=default;
    sp(GraphicBuffer*);
    sp(const sp&);
    sp& operator=(const sp&);
    ~sp();
};
struct GraphicBuffer : ANativeWindowBuffer {
    int references=1;
    explicit GraphicBuffer(buffer_handle_t value) { handle=value; }
    static sp<GraphicBuffer> from(ANativeWindowBuffer* buffer) { return static_cast<GraphicBuffer*>(buffer); }
    void release() { if (--references==0) const_cast<native_handle_t*>(handle)->alive=false; }
};
sp<GraphicBuffer>::sp(GraphicBuffer* value):pointer(value) { if (pointer) ++pointer->references; }
sp<GraphicBuffer>::sp(const sp& other):sp(other.pointer) {}
sp<GraphicBuffer>& sp<GraphicBuffer>::operator=(const sp& other) {
    if (other.pointer) ++other.pointer->references;
    if (pointer) pointer->release();
    pointer=other.pointer;
    return *this;
}
sp<GraphicBuffer>::~sp() { if (pointer) pointer->release(); }

struct Crop { int left=-1,top=-1,right=-1,bottom=-1; };
struct ANativeWindow {
    int queued=0,canceled=0;
    BoundaryMutex* mutex=nullptr;
    int queueBuffer(ANativeWindow*,ANativeWindowBuffer*,int) { check(mutex->held,"queue locked"); ++queued; return 0; }
    int cancelBuffer(ANativeWindow*,ANativeWindowBuffer*,int) { check(mutex->held,"cancel locked"); ++canceled; return 0; }
    int query(ANativeWindow*,int,int* count) { *count=2; return 0; }
    int setSwapInterval(ANativeWindow*,int) { return 0; }
};
static ANativeWindowBuffer* nextBuffer;
static std::function<void()> dequeueHook;
static int native_window_dequeue_buffer_and_wait(ANativeWindow* window,ANativeWindowBuffer** result) {
    check(!window->mutex->held,"dequeue waits outside map mutex");
    if (dequeueHook) dequeueHook();
    *result=nextBuffer;
    return 0;
}
template<class... T> int native_window_api_disconnect(T...) { return 0; }
template<class... T> int native_window_api_connect(T...) { return 0; }
template<class... T> int native_window_set_scaling_mode(T...) { return 0; }
template<class... T> int native_window_set_buffers_transform(T...) { return 0; }
template<class... T> int native_window_set_buffers_dimensions(T...) { return 0; }
template<class... T> int native_window_set_buffers_format(T...) { return 0; }
template<class... T> int native_window_set_usage(T...) { return 0; }
template<class... T> int native_window_set_crop(T...) { return 0; }
static int native_window_set_buffer_count(ANativeWindow* window,uint32_t) { check(window!=nullptr,"count window exists"); return 0; }
struct Device {
    BoundaryMutex* mutex=nullptr;
    Status setPreviewWindow(void*) { check(!mutex->held,"HIDL window call outside mutex"); return Status::OK; }
};
struct CameraProviderManager { static int mapToStatusT(Status status) { return status==Status::OK ? 0 : -1; } };
struct CameraHardwareInterface {
    using dequeueBuffer_cb=std::function<void(Status,uint64_t,hidl_handle,uint32_t)>;
    using getMinUndequeuedBufferCount_cb=std::function<void(Status,uint32_t)>;
    BoundaryMutex mBufferIdMapLock;
    sp<ANativeWindow> mPreviewWindow;
    sp<Device> mHidlDevice;
    std::unordered_map<buffer_handle_t,uint64_t> mBufferIdMap;
    std::unordered_map<uint64_t,ANativeWindowBuffer*> mReversedBufMap;
    uint64_t mNextBufferId=1,mBufferGeneration=0;
    int mPreviewScalingMode=NOT_SET,mPreviewTransform=NOT_SET,mPreviewWidth=NOT_SET,mPreviewHeight=NOT_SET,mPreviewFormat=NOT_SET,mPreviewSwapInterval=NOT_SET;
    uint64_t mPreviewUsage=0;
    Crop mPreviewCrop;
    int setPreviewScalingMode(int) { return 0; }
    int setPreviewTransform(int) { return 0; }
    std::pair<bool,uint64_t> getBufferIdLocked(ANativeWindowBuffer*);
    void cleanupCirculatingBuffers();
    void cleanupCirculatingBuffersLocked();
    hardware::Return<void> dequeueBuffer(dequeueBuffer_cb);
    hardware::Return<void> getMinUndequeuedBufferCount(getMinUndequeuedBufferCount_cb);
    hardware::Return<Status> enqueueBuffer(uint64_t);
    hardware::Return<Status> cancelBuffer(uint64_t);
    hardware::Return<Status> setBufferCount(uint32_t);
    status_t setPreviewWindow(const sp<ANativeWindow>&);
};
"""
CASES = r"""
int main() {
    CameraHardwareInterface camera;
    int replies=0;
    camera.dequeueBuffer([&](Status status,uint64_t id,hidl_handle handle,uint32_t stride) {
        ++replies; check(!camera.mBufferIdMapLock.held,"HIDL reply outside mutex"); check(status==Status::INTERNAL_ERROR && id==0 && !handle.pointer && stride==0,"missing dequeue reply");
    });
    camera.getMinUndequeuedBufferCount([&](Status status,uint32_t count) {
        ++replies; check(!camera.mBufferIdMapLock.held,"HIDL reply outside mutex"); check(status==Status::INTERNAL_ERROR && count==0,"missing count reply");
    });
    check(replies==2,"one callback per missing window");
    check(static_cast<Status>(camera.setBufferCount(2))==Status::INTERNAL_ERROR,"missing set count");
    Device device;
    device.mutex=&camera.mBufferIdMapLock;
    camera.mHidlDevice=&device;
    ANativeWindow oldWindow,newWindow;
    oldWindow.mutex=newWindow.mutex=&camera.mBufferIdMapLock;
    native_handle_t handle;
    GraphicBuffer buffer{&handle};
    nextBuffer=&buffer;
    camera.setPreviewWindow(&oldWindow);
    uint64_t validId=0;
    camera.dequeueBuffer([&](Status status,uint64_t id,hidl_handle,uint32_t) { check(!camera.mBufferIdMapLock.held,"success reply outside mutex"); check(status==Status::OK,"valid dequeue"); validId=id; });
    check(static_cast<Status>(camera.enqueueBuffer(validId))==Status::OK && oldWindow.queued==1,"valid enqueue");
    check(static_cast<Status>(camera.cancelBuffer(validId))==Status::OK && oldWindow.canceled==1,"valid cancel");
    camera.setPreviewWindow(&newWindow);
    check(camera.mBufferIdMap.empty() && camera.mReversedBufMap.empty(),"window clears maps");
    check(static_cast<Status>(camera.enqueueBuffer(validId))==Status::ILLEGAL_ARGUMENT && newWindow.queued==0,"old id rejected");
    camera.setPreviewWindow(&oldWindow);
    dequeueHook=[&]() { camera.setPreviewWindow(&newWindow); };
    camera.dequeueBuffer([&](Status status,uint64_t id,hidl_handle,uint32_t) { check(status==Status::INTERNAL_ERROR && id==0,"window changed during dequeue"); });
    check(oldWindow.canceled==2 && camera.mReversedBufMap.empty(),"old window cancels stale dequeue");
    dequeueHook=[&]() { camera.cleanupCirculatingBuffers(); };
    camera.dequeueBuffer([&](Status status,uint64_t id,hidl_handle,uint32_t) { check(status==Status::INTERNAL_ERROR && id==0,"generation changed during dequeue"); });
    check(newWindow.canceled==1,"same window cancels stale generation");

    dequeueHook=nullptr;
    camera.setPreviewWindow(&oldWindow);
    native_handle_t replyHandle;
    GraphicBuffer replyBuffer{&replyHandle};
    nextBuffer=&replyBuffer;
    dequeueHook=[&]() {
        afterUnlock=[&]() {
            camera.setPreviewWindow(&newWindow);
            replyBuffer.release();
        };
    };
    camera.dequeueBuffer([&](Status status,uint64_t,hidl_handle borrowed,uint32_t) {
        check(status==Status::OK && borrowed.pointer==&replyHandle && borrowed.pointer->alive,
              "reply retains buffer after slot release");
    });
    check(!replyHandle.alive && replyBuffer.references==0,"reply releases final buffer owner");
    return failures ? 1 : 0;
}
"""


class PreviewBoundaries(unittest.TestCase):
    def test_preview_production_methods(self):
        source = (ROOT / "device1/CameraHardwareInterface.cpp").read_text()
        signatures = [
            "std::pair<bool, uint64_t> CameraHardwareInterface::getBufferIdLocked(",
            "void CameraHardwareInterface::cleanupCirculatingBuffers(",
            "void CameraHardwareInterface::cleanupCirculatingBuffersLocked(",
            "CameraHardwareInterface::dequeueBuffer(",
            "CameraHardwareInterface::getMinUndequeuedBufferCount(",
            "CameraHardwareInterface::enqueueBuffer(",
            "CameraHardwareInterface::cancelBuffer(",
            "CameraHardwareInterface::setBufferCount(",
            "status_t CameraHardwareInterface::setPreviewWindow(",
        ]
        methods = []
        for signature in signatures:
            body = function(source, signature)
            if signature.startswith("CameraHardwareInterface::"):
                result = (
                    "void"
                    if "dequeueBuffer(" in signature
                    or "getMinUndequeuedBufferCount(" in signature
                    else "Status"
                )
                body = "hardware::Return<" + result + ">\n" + body
            methods.append(
                body.replace(
                    "std::lock_guard<std::mutex>", "std::lock_guard<BoundaryMutex>"
                )
            )
        output = Path(os.environ["TEST_OUTPUT_DIR"]).resolve(strict=True)
        fixture = output / "hal1_preview_boundaries.cpp"
        fixture.write_text(PREFIX + "\n".join(methods) + CASES)
        binary = output / "hal1_preview_boundaries"
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

    def test_registration_and_transport_contracts(self):
        source = (ROOT / "device1/CameraHardwareInterface.cpp").read_text()
        registration = function(
            source,
            "hardware::Return<uint32_t> CameraHardwareInterface::registerMemory(",
        )
        self.assertLess(
            registration.index("descriptor.getNativeHandle() == nullptr"),
            registration.index("descriptor->numFds"),
        )
        header = (ROOT / "device1/CameraHardwareInterface.h").read_text()
        for field in [
            "mNotifyCb",
            "mDataCb",
            "mDataCbTimestamp",
            "mDataCbTimestampBatch",
            "mCbUser",
        ]:
            self.assertIn(field + " = nullptr;", header)
        provider = (ROOT / "common/CameraProviderManager.cpp").read_text()
        constructor_start = provider.index(
            "CameraProviderManager::ProviderInfo::DeviceInfo1::DeviceInfo1("
        )
        constructor_end = provider.index(
            "CameraProviderManager::ProviderInfo::DeviceInfo1::~DeviceInfo1()",
            constructor_start,
        )
        constructor = provider[constructor_start:constructor_end]
        close = constructor[constructor.index("ret = interface->close();") :]
        failure = close[: close.index("if (res != OK)")]
        self.assertIn("res = DEAD_OBJECT;", failure)
        self.assertIn("ret.description()", failure)


if __name__ == "__main__":
    unittest.main()
