"""Execute the recording listener Binder boundary with malformed memory parcels."""

import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(
    os.environ.get("CAMERA_SOURCE_CHECKOUT", Path(__file__).resolve().parents[4])
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
#include <vector>
#include <sys/mman.h>
#define ALOGV(...) ((void)0)
#define ALOGE(...) ((void)0)
#define CHECK_INTERFACE(...) ((void)0)
using status_t=int;
using nsecs_t=int64_t;
constexpr int OK=0,NO_ERROR=0,BAD_VALUE=-22;
constexpr uint32_t DATA_CALLBACK_TIMESTAMP=1,RECORDING_FRAME_HANDLE_CALLBACK_TIMESTAMP=2,
    RECORDING_FRAME_HANDLE_CALLBACK_TIMESTAMP_BATCH=3;
template<class T> struct sp {
    T* pointer=nullptr;
    sp()=default;
    sp(T* value):pointer(value) {}
    T* operator->() const { return pointer; }
    bool operator==(std::nullptr_t) const { return pointer==nullptr; }
};
struct IMemoryHeap {
    int id=7;
    size_t bytes=128;
    void* base=reinterpret_cast<void*>(4096);
    size_t getSize() const { return bytes; }
    int getHeapID() const { return id; }
    void* getBase() const { return base; }
};
struct IMemory {
    IMemoryHeap* heap=nullptr;
    ssize_t offset=16;
    size_t size=32;
    sp<IMemoryHeap> getMemory(ssize_t* start,size_t* count) { *start=offset; *count=size; return heap; }
};
struct IBinder { IMemory* memory; };
template<class T> sp<T> interface_cast(const sp<IBinder>& binder) { return binder==nullptr ? nullptr : binder->memory; }
struct native_handle_t {};
int native_handle_close(native_handle_t*) { return 0; }
int native_handle_delete(native_handle_t*) { return 0; }
struct Parcel {
    IBinder* binder;
    status_t timestampStatus=OK,typeStatus=OK,binderStatus=OK;
    status_t readInt64(int64_t* value) const { *value=91; return timestampStatus; }
    int64_t readInt64() const { return 91; }
    status_t readInt32(int32_t* value) const { *value=32; return typeStatus; }
    int32_t readInt32() const { return 32; }
    status_t readStrongBinder(sp<IBinder>* value) const { *value=binder; return binderStatus; }
    sp<IBinder> readStrongBinder() const { return binder; }
    status_t readUint32(uint32_t* value) const { *value=0; return OK; }
    size_t dataAvail() const { return 0; }
    native_handle_t* readNativeHandle() const { return nullptr; }
};
struct BBinder { static status_t onTransact(uint32_t,const Parcel&,Parcel*,uint32_t) { return -1; } };
struct BnCameraRecordingProxyListener {
    int callbacks=0;
    void dataCallbackTimestamp(int64_t,int32_t,const sp<IMemory>&) { ++callbacks; }
    void recordingFrameHandleCallbackTimestamp(int64_t,native_handle_t*) {}
    void recordingFrameHandleCallbackTimestampBatch(const std::vector<nsecs_t>&,const std::vector<native_handle_t*>&) {}
    status_t onTransact(uint32_t,const Parcel&,Parcel*,uint32_t);
};
static int failures;
static void check(bool pass,const char* message) { if (!pass) { ++failures; std::fprintf(stderr,"FAIL: %s\n",message); } }
"""
CASES = r"""
int main() {
    for (int scenario=-1; scenario<13; ++scenario) {
        IMemoryHeap heap;
        IMemory memory{&heap};
        IBinder binder{&memory};
        Parcel parcel{&binder};
        BnCameraRecordingProxyListener listener;
        switch (scenario) {
            case 0: parcel.binder=nullptr; break;
            case 1: binder.memory=nullptr; break;
            case 2: memory.heap=nullptr; break;
            case 3: memory.offset=-1; break;
            case 4: memory.size=0; break;
            case 5: memory.size=129; break;
            case 6: memory.offset=97; break;
            case 7: heap.id=-1; break;
            case 8: heap.base=MAP_FAILED; break;
            case 9: heap.base=nullptr; break;
            case 10: parcel.timestampStatus=BAD_VALUE; break;
            case 11: parcel.typeStatus=BAD_VALUE; break;
            case 12: parcel.binderStatus=BAD_VALUE; break;
        }
        status_t result=listener.onTransact(DATA_CALLBACK_TIMESTAMP,parcel,nullptr,0);
        if (scenario<0) check(result==OK && listener.callbacks==1,"valid mapped memory dispatches once");
        else check(result==BAD_VALUE && listener.callbacks==0,"malformed memory stays outside callback");
    }
    return failures ? 1 : 0;
}
"""


class ListenerMemory(unittest.TestCase):
    def test_parcel_memory_validation(self):
        source = (ROOT / "camera/ICameraRecordingProxyListener.cpp").read_text()
        method = function(
            source, "status_t BnCameraRecordingProxyListener::onTransact("
        )
        output = Path(os.environ["TEST_OUTPUT_DIR"]).resolve(strict=True)
        fixture = output / "recording_listener_memory.cpp"
        binary = fixture.with_suffix("")
        fixture.write_text(PREFIX + method + CASES)
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
