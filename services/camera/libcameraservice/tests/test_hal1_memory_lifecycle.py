"""Compile production HAL1 heap ownership against checked memory collaborators.

The fixture retains RefBase ownership and substitutes mapping/allocation results.
The signed-offset variants exercise LP64 and the ILP32 registration boundary.
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
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <sys/mman.h>
#include <unistd.h>
#include <unordered_map>
#include <functional>
#include <stdexcept>
#define ALOGE(...) ((void)0)
#define ALOGI(...) ((void)0)
#define ALOGV(...) ((void)0)
#define CC_LIKELY(value) (value)
using uint_t=unsigned;
static int failures, heaps, buffers, allocations, mappedHeaps;
static int mappingId=7;
static bool mappingFails, bufferAllocationFails;
static std::function<void()> mappingHook;
static void check(bool pass,const char* message) {
    if (!pass) { ++failures; std::fprintf(stderr,"FAIL: %s\n",message); }
}
struct RefBase {
    mutable int refs=0;
    void incStrong(const void*) const { ++refs; }
    void decStrong(const void*) const { if (--refs==0) delete this; }
    virtual ~RefBase()=default;
};
template<class T> struct sp {
    T* pointer=nullptr;
    sp()=default;
    sp(std::nullptr_t) {}
    sp(T* value):pointer(value) { if (pointer) pointer->incStrong(this); }
    sp(const sp& other):sp(other.pointer) {}
    ~sp() { if (pointer) pointer->decStrong(this); }
    sp& operator=(const sp& other) { sp copy(other); std::swap(pointer,copy.pointer); return *this; }
    T* operator->() const { return pointer; }
    T* get() const { return pointer; }
    bool operator==(std::nullptr_t) const { return pointer==nullptr; }
    bool operator!=(std::nullptr_t) const { return pointer!=nullptr; }
    void clear() { *this=nullptr; }
    static void* operator new[](size_t size) {
        if (size>1024*1024) throw std::bad_alloc();
        return ::operator new[](size);
    }
    static void operator delete[](void* value) { ::operator delete[](value); }
};
struct MemoryHeapBase : RefBase {
    size_t bytes;
    unsigned char storage[256]={};
    int id;
    explicit MemoryHeapBase(size_t size):MemoryHeapBase(1,size) {}
    MemoryHeapBase(int,size_t size):bytes(size),id(mappingFails ? -1 : mappingId) {
        ++heaps; ++mappedHeaps;
        if (mappingHook) { auto hook=mappingHook; mappingHook=nullptr; hook(); }
    }
    ~MemoryHeapBase() { --heaps; }
    int getHeapID() const { return id; }
    void* base() { return mappingFails ? MAP_FAILED : storage; }
    size_t getSize() const { return bytes; }
};
struct MemoryBase : RefBase {
    sp<MemoryHeapBase> heap;
    ssize_t offset;
    size_t bytes;
    MemoryBase(const sp<MemoryHeapBase>& value,ssize_t start,size_t count):heap(value),offset(start),bytes(count) { ++buffers; ++allocations; }
    ~MemoryBase() { --buffers; }
    static void* operator new(size_t size,const std::nothrow_t&) noexcept {
        return bufferAllocationFails ? nullptr : ::operator new(size,std::nothrow);
    }
    static void* operator new(size_t size) { return ::operator new(size); }
    static void operator delete(void* value) { ::operator delete(value); }
    void* unsecurePointer() { return static_cast<unsigned char*>(heap->base())+offset; }
};
struct camera_memory_t { void* data; size_t size; void* handle; void (*release)(camera_memory_t*); };
struct native_handle_t { int numFds=1; int data[1]={3}; };
namespace hardware {
    struct hidl_handle {
        native_handle_t* value=nullptr;
        const native_handle_t* getNativeHandle() const { return value; }
        const native_handle_t* operator->() const { return value; }
    };
    template<class T> struct Return { T value; Return(T data):value(data) {} operator T() const { return value; } };
    template<> struct Return<void> {};
    Return<void> Void() { return {}; }
}
struct Device : RefBase {
    struct Result {
        bool success;
        mutable bool checked=false;
        bool isOk() const { checked=true; return success; }
        ~Result() { if (!success && !checked) std::abort(); }
    };
    std::function<void()> closeHook;
    bool transport=true;
    Result close() { if (closeHook) closeHook(); return {transport}; }
};
struct Name { const char* string() const { return "0"; } };
struct CameraHardwareInterface {
    static camera_memory_t* sGetMemory(int,size_t,uint_t,void*);
    static void sPutMemory(camera_memory_t*);
    void releaseMemoryPools();
    void release();
    ~CameraHardwareInterface();
    hardware::Return<uint32_t> registerMemory(const hardware::hidl_handle&,uint32_t,uint32_t);
    hardware::Return<void> unregisterMemory(uint32_t);
    std::mutex mHidlMemPoolMapLock;
    std::unordered_map<int,camera_memory_t*> mHidlMemPoolMap;
    bool mMemoryRegistrationClosed=false;
    sp<Device> mHidlDevice;
    Name mName;
    void cleanupCirculatingBuffers() {}
"""

CASES = r"""
int main() {
    native_handle_t descriptor;
    if (getenv("TEST_HEAP_CASE") && std::string(getenv("TEST_HEAP_CASE"))=="dimensions") {
        for (const auto& dimensions : {std::pair<size_t,unsigned>{0,1},{1,0},
                {static_cast<size_t>(std::numeric_limits<HeapOffset>::max()),2}}) {
            const int before=mappedHeaps;
            auto* memory=CameraHardwareInterface::sGetMemory(3,dimensions.first,dimensions.second,nullptr);
            check(memory==nullptr,"reject dimensions before heap construction");
            check(mappedHeaps==before,"invalid dimensions allocate zero heaps");
            if (memory) memory->release(memory);
        }
        mappingFails=true;
        auto* invalid=CameraHardwareInterface::sGetMemory(3,16,4,nullptr);
        check(invalid==nullptr,"mapping failure rejected");
        if (invalid) invalid->release(invalid);
        mappingFails=false;
        check(heaps==0 && buffers==0,"failed allocation releases resources");
        return failures ? 1 : 0;
    }
    if (getenv("TEST_HEAP_CASE") && std::string(getenv("TEST_HEAP_CASE"))=="slots") {
        CameraHardwareInterface camera;
        camera.registerMemory({&descriptor},16,4);
        auto* raw=static_cast<CameraHardwareInterface::CameraHeapMemory*>(camera.mHidlMemPoolMap.at(7)->handle);
        sp<CameraHardwareInterface::CameraHeapMemory> callbackOwner(raw);
        auto first=slotBuffer(*raw,0);
        auto last=slotBuffer(*raw,3);
        check(first!=nullptr && first->offset==0 && first->bytes==16,"first slot region");
        check(last!=nullptr && last->offset==48 && last->bytes==16,"last slot region");
        check(slotBuffer(*raw,4)==nullptr,"out of range slot rejected");
        bufferAllocationFails=true;
        check(slotBuffer(*raw,0)==nullptr,"slot allocation failure returns null");
        bufferAllocationFails=false;
        camera.release();
        check(heaps==1,"callback owner retains drained pool");
        callbackOwner.clear();
        check(heaps==1,"memory wrappers retain heap after pool destruction");
        first.clear(); last.clear();
        check(heaps==0 && buffers==0,"last callback wrapper releases mapped heap");
        return failures ? 1 : 0;
    }
    if (getenv("TEST_HEAP_CASE") && std::string(getenv("TEST_HEAP_CASE"))=="count") {
        auto* memory=CameraHardwareInterface::sGetMemory(3,1,10000000,nullptr);
        check(memory!=nullptr,"large representable pool maps");
        check(allocations==0,"registration allocation is independent of count");
        if (memory) memory->release(memory);
        check(heaps==0 && buffers==0,"large count releases its one heap");
        return failures ? 1 : 0;
    }
    {
        CameraHardwareInterface camera;
        check(camera.registerMemory({},16,4)==0,"null descriptor rejected");
        check(camera.registerMemory({&descriptor},16,4)==7,"valid pool registered");
        check(camera.registerMemory({&descriptor},16,4)==0,"colliding pool released");
        check(heaps==1,"collision retains only original pool");
        camera.unregisterMemory(7);
        camera.unregisterMemory(7);
        check(heaps==0,"unregister releases exactly one owner");
        check(camera.registerMemory({&descriptor},16,4)==7,"register after unregister");
        camera.mHidlDevice=new Device;
        camera.mHidlDevice->closeHook=[&]() { camera.unregisterMemory(7); };
        camera.release();
        check(heaps==0 && camera.mHidlMemPoolMap.empty(),"close unregister and drain are idempotent");
        check(camera.registerMemory({&descriptor},16,4)==0,"late registration rejected");
        check(heaps==0,"late registration releases its allocated heap");
    }
    {
        CameraHardwareInterface camera;
        camera.registerMemory({&descriptor},16,4);
        mappingHook=[&]() { camera.release(); };
        mappingId=8;
        check(camera.registerMemory({&descriptor},16,4)==0,"registration racing teardown rejected");
        mappingId=7;
        check(camera.mHidlMemPoolMap.empty() && heaps==0,"racing registration leaks zero heaps");
    }
    {
        CameraHardwareInterface camera;
        camera.registerMemory({&descriptor},16,4);
        camera.release();
        camera.release();
        check(camera.mHidlMemPoolMap.empty() && heaps==0,"release drains orphaned registration once");
    }
    {
        CameraHardwareInterface camera;
        camera.registerMemory({&descriptor},16,4);
    }
    check(heaps==0,"destructor drains without device close");
    {
        CameraHardwareInterface camera;
        camera.registerMemory({&descriptor},16,4);
        camera.mHidlDevice=new Device;
        camera.mHidlDevice->transport=false;
        camera.release();
        check(heaps==0,"failed close still drains memory");
    }
    {
        CameraHardwareInterface camera;
        camera.registerMemory({&descriptor},16,4);
        camera.mHidlDevice=new Device;
        camera.mHidlDevice->transport=false;
    }
    check(heaps==0,"destructor checks failed close and drains memory");
    mappingId=0;
    {
        CameraHardwareInterface camera;
        check(camera.registerMemory({&descriptor},16,4)==0,"zero pool ID stays failure sentinel");
    }
    mappingId=7;
    check(heaps==0 && buffers==0,"all pools and wrappers released");
    return failures ? 1 : 0;
}
"""


class MemoryLifecycle(unittest.TestCase):
    def compile_fixture(self, offset_type):
        source = (ROOT / "device1/CameraHardwareInterface.cpp").read_text()
        header = (ROOT / "device1/CameraHardwareInterface.h").read_text()
        heap = function(header, "class CameraHeapMemory :")
        methods = "\n".join(
            function(source, signature)
            for signature in [
                "camera_memory_t* CameraHardwareInterface::sGetMemory(",
                "void CameraHardwareInterface::sPutMemory(",
                "hardware::Return<uint32_t> CameraHardwareInterface::registerMemory(",
                "hardware::Return<void> CameraHardwareInterface::unregisterMemory(",
                "void CameraHardwareInterface::release()",
                "CameraHardwareInterface::~CameraHardwareInterface()",
            ]
        )
        if "void CameraHardwareInterface::releaseMemoryPools()" in source:
            methods += function(
                source, "void CameraHardwareInterface::releaseMemoryPools()"
            )
        methods = methods.replace(
            "std::numeric_limits<ssize_t>", "std::numeric_limits<HeapOffset>"
        )
        output = Path(os.environ["TEST_OUTPUT_DIR"]).resolve(strict=True)
        fixture = output / ("hal1_memory_" + offset_type + ".cpp")
        binary = fixture.with_suffix("")
        slot_method = (
            "return heap.getBuffer(index);"
            if "sp<MemoryBase> getBuffer(" in heap
            else "return index < heap.mNumBufs ? heap.mBuffers[index] : nullptr;"
        )
        slot_helper = (
            "sp<MemoryBase> slotBuffer(CameraHardwareInterface::CameraHeapMemory& heap,uint32_t index) {"
            + slot_method
            + "}\n"
        )
        fixture.write_text(
            PREFIX
            + heap
            + ";\n};\nusing HeapOffset="
            + offset_type
            + ";\n"
            + methods
            + slot_helper
            + CASES
        )
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
        return binary

    def test_registration_dimensions_and_constant_space(self):
        for offset_type in ("int32_t", "ssize_t"):
            binary = self.compile_fixture(offset_type)
            for case in ("dimensions", "count", "slots", "lifecycle"):
                with self.subTest(offset_type=offset_type, case=case):
                    environment = dict(os.environ, TEST_HEAP_CASE=case)
                    subprocess.run([str(binary)], env=environment, check=True)


if __name__ == "__main__":
    unittest.main()
