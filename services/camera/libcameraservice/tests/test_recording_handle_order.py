"""Execute CameraSource production callbacks and ordered handle returns."""

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
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <functional>
#include <list>
#include <vector>
#define ALOGV(...) ((void)0)
#define ALOGW(...) ((void)0)
#define ALOGE(...) ((void)0)
#define CHECK(value) assert(value)
#define __unused __attribute__((unused))
constexpr int TIMED_OUT=-110;
constexpr int kMetadataBufferTypeNativeHandleSource=3;
struct native_handle_t { int id; int closes=0; int deletes=0; };
int native_handle_close(native_handle_t* handle) { ++handle->closes; return 0; }
int native_handle_delete(native_handle_t* handle) { ++handle->deletes; return 0; }
static int failures;
void check(bool pass,const char* message) { if (!pass) { ++failures; std::fprintf(stderr,"FAIL: %s\n",message); } }
struct Mutex {
    struct Autolock { explicit Autolock(Mutex&) {} };
};
struct Condition {
    std::function<void()> onWait;
    int signals=0;
    void signal() { ++signals; }
    int waitRelative(Mutex&,int64_t) {
        if (onWait) { auto hook=onWait; onWait=nullptr; hook(); return 0; }
        return TIMED_OUT;
    }
};
struct VideoNativeHandleMetadata { int eType=0; native_handle_t* pHandle=nullptr; };
struct IMemoryHeap {
    int getHeapID() const { return 7; }
    void* getBase() const { return nullptr; }
};
static IMemoryHeap sharedHeap;
struct IMemory {
    VideoNativeHandleMetadata metadata;
    size_t bytes=sizeof(metadata);
    bool mapped=true;
    void* unsecurePointer() { return mapped ? &metadata : nullptr; }
    size_t size() const { return bytes; }
    IMemoryHeap* getMemory(ssize_t* offset,size_t* size) {
        *offset=0; *size=bytes; return &sharedHeap;
    }
};
template<class T> struct sp {
    T* pointer=nullptr;
    sp()=default;
    sp(T* value):pointer(value) {}
    T* operator->() const { return pointer; }
    bool operator!=(std::nullptr_t) const { return pointer!=nullptr; }
    bool operator==(std::nullptr_t) const { return pointer==nullptr; }
};
struct Endpoint {
    std::vector<int> returned;
    int batches=0;
    void releaseRecordingFrame(const sp<IMemory>&) {}
    void releaseRecordingFrameHandle(native_handle_t* handle) {
        returned.push_back(handle->id); native_handle_close(handle); native_handle_delete(handle);
    }
    void releaseRecordingFrameHandleBatch(const std::vector<native_handle_t*>& handles) {
        ++batches;
        for (auto* handle:handles) releaseRecordingFrameHandle(handle);
    }
};
struct IPCThreadState {
    static IPCThreadState* self() { static IPCThreadState state; return &state; }
    int64_t clearCallingIdentity() { return 3; }
    void restoreCallingIdentity(int64_t token) { check(token==3,"identity restored"); }
};
namespace hardware { struct ICamera { static constexpr int VIDEO_BUFFER_MODE_BUFFER_QUEUE=0; }; }
struct VideoNativeMetadata { void* pBuffer; };
struct BufferItem {};
struct BufferItemConsumer { void releaseBuffer(const BufferItem&) {} };
struct BufferItemMap {
    ssize_t indexOfKey(void*) { return -1; }
    BufferItem valueAt(ssize_t) { return {}; }
    void removeItemsAt(ssize_t) {}
};
constexpr ssize_t NAME_NOT_FOUND=-1;
struct CameraSource {
    Mutex mLock,mBatchLock;
    Condition mFrameAvailableCondition,mMemoryBaseAvailableCond;
    static constexpr int64_t kMemoryBaseAvailableTimeoutNs=1;
    std::list<sp<IMemory>> mMemoryBases,mFramesReceived;
    std::list<int64_t> mFrameTimes;
    std::deque<uint32_t> mInflightBatchSizes;
    std::vector<native_handle_t*> mInflightReturnedHandles;
    std::vector<sp<IMemory>> mInflightReturnedMemorys;
    int mVideoBufferMode=1;
    sp<IMemoryHeap> mMemoryHeapBase=&sharedHeap;
    sp<BufferItemConsumer> mVideoBufferConsumer;
    BufferItemMap mReceivedBufferItemMap;
    void releaseRecordingFrame(const sp<IMemory>&);
    int mNumFramesReceived=0,decisions=0,rawReturns=0;
    bool mStarted=true;
    int64_t mStartTimeUs=0,mFirstFrameTimeUs=0;
    Endpoint* mCameraRecordingProxy=nullptr;
    Endpoint* mCamera=nullptr;
    struct PendingRecordingHandle { native_handle_t* handle; bool ready; };
    std::deque<PendingRecordingHandle> mPendingRecordingHandles;
    bool shouldSkipFrameLocked(int64_t timestamp) { ++decisions; return !mStarted || timestamp<0; }
    void releaseOneRecordingFrame(const sp<IMemory>&) { ++rawReturns; }
    void markRecordingFrameReturned(native_handle_t*);
    void returnReadyRecordingFrames();
    void releaseRecordingFrameHandle(native_handle_t*);
    void releaseRecordingFrameHandleBatch(const std::vector<native_handle_t*>&);
    void recordingFrameHandleCallbackTimestamp(int64_t,native_handle_t*);
    void recordingFrameHandleCallbackTimestampBatch(const std::vector<int64_t>&,const std::vector<native_handle_t*>&);
    void dataCallbackTimestamp(int64_t,int32_t,const sp<IMemory>&);
};
"""

CASES = r"""
int main(int argc,char** argv) {
    if (argc>1 && argv[1][0]=='n') {
        CameraSource source;
        source.dataCallbackTimestamp(1,32,nullptr);
        source.dataCallbackTimestamp(-1,32,nullptr);
        IMemory invalid;
        invalid.bytes=0;
        source.dataCallbackTimestamp(1,32,&invalid);
        invalid.bytes=sizeof(invalid.metadata); invalid.mapped=false;
        source.dataCallbackTimestamp(1,32,&invalid);
        check(source.decisions==0 && source.mNumFramesReceived==0 && source.rawReturns==0,
              "invalid memory preserves callback state before skip or dispatch");
        return failures ? 1 : 0;
    }
    for (int route=0; route<3; ++route) {
        CameraSource source;
        Endpoint endpoint;
        if (route==0) source.mCameraRecordingProxy=&endpoint;
        if (route==1) source.mCamera=&endpoint;
        IMemory memory;
        source.mMemoryBases.push_back(&memory);
        native_handle_t first{1},dropped{2};
        source.recordingFrameHandleCallbackTimestamp(1,&first);
        source.recordingFrameHandleCallbackTimestamp(-1,&dropped);
        check(first.closes==0 && dropped.closes==0,"drop waits behind encoder-owned frame");
        source.releaseRecordingFrameHandle(&first);
        check(first.closes==1 && dropped.closes==1 && first.deletes==1 && dropped.deletes==1,
              "ready delivery prefix consumes every handle once");
        if (route<2) check(endpoint.returned==std::vector<int>({1,2}),"returned handles preserve HAL slot order");
        check(source.mPendingRecordingHandles.empty(),"finished prefix drains pending queue");
    }
    {
        CameraSource source;
        Endpoint endpoint;
        source.mCameraRecordingProxy=&endpoint;
        IMemory firstMemory,secondMemory;
        source.mMemoryBases={&firstMemory,&secondMemory};
        native_handle_t first{1},second{2},dropped{3};
        source.recordingFrameHandleCallbackTimestamp(1,&first);
        source.recordingFrameHandleCallbackTimestamp(2,&second);
        source.recordingFrameHandleCallbackTimestamp(-1,&dropped);
        source.releaseRecordingFrameHandle(&second);
        check(endpoint.returned.empty(),"out-of-order encoder completion retains later handles");
        source.releaseRecordingFrameHandle(&first);
        check(endpoint.returned==std::vector<int>({1,2,3}),"encoder completion and drop share delivery order");
    }
    {
        CameraSource source;
        Endpoint endpoint;
        source.mCameraRecordingProxy=&endpoint;
        IMemory firstMemory,thirdMemory;
        source.mMemoryBases={&firstMemory,&thirdMemory};
        native_handle_t first{1},second{2},third{3},fourth{4};
        source.recordingFrameHandleCallbackTimestampBatch({1,-1,2,-1},{&first,&second,&third,&fourth});
        check(endpoint.returned.empty(),"interleaved batch drops wait for encoded frames");
        source.releaseRecordingFrameHandleBatch({&third,&first});
        check(endpoint.returned==std::vector<int>({1,2,3,4}) && endpoint.batches==1,
              "batch completion drains a contiguous prefix in one HAL batch");
    }
    {
        CameraSource source;
        Endpoint endpoint;
        source.mCameraRecordingProxy=&endpoint;
        IMemory memory;
        source.mMemoryBases={&memory};
        native_handle_t first{1},timeout{2};
        source.recordingFrameHandleCallbackTimestamp(1,&first);
        source.recordingFrameHandleCallbackTimestamp(2,&timeout);
        check(endpoint.returned.empty(),"memory timeout preserves return order");
        source.releaseRecordingFrameHandle(&first);
        check(endpoint.returned==std::vector<int>({1,2}),"timeout handle drains after older frame");
    }
    {
        CameraSource source;
        Endpoint endpoint;
        source.mCameraRecordingProxy=&endpoint;
        native_handle_t first{1},second{2};
        source.recordingFrameHandleCallbackTimestampBatch({1},{&first,&second});
        check(endpoint.returned==std::vector<int>({1,2}) && source.mNumFramesReceived==0,
              "mismatched batch returns all supplied handles without indexing timestamps");
    }
    {
        CameraSource source;
        Endpoint endpoint;
        source.mCameraRecordingProxy=&endpoint;
        IMemory firstMemory,secondMemory;
        source.mMemoryBases={&firstMemory,&secondMemory};
        native_handle_t first{1},second{2},third{3},fourth{4};
        source.mMemoryBaseAvailableCond.onWait=[&]() {
            check(source.mFrameAvailableCondition.signals==2,
                  "partial batch signals queued frames before waiting for wrappers");
            auto ready=source.mFramesReceived;
            source.mFramesReceived.clear();
            for (auto frame:ready) source.releaseRecordingFrame(frame);
            check(source.mMemoryBases.size()==2,"early encoder completions recycle wrappers");
        };
        source.recordingFrameHandleCallbackTimestampBatch({1,2,3,4},
                {&first,&second,&third,&fourth});
        auto ready=source.mFramesReceived;
        source.mFramesReceived.clear();
        for (auto frame:ready) source.releaseRecordingFrame(frame);
        check(endpoint.returned==std::vector<int>({1,2,3,4}),
              "batch larger than wrapper pool returns every frame without count starvation");
        check(source.mMemoryBases.size()==2 && source.mPendingRecordingHandles.empty(),
              "batch interleaving retains zero wrappers or native handles");
    }
    for (bool batch : {false,true}) {
        CameraSource source;
        Endpoint endpoint;
        source.mCameraRecordingProxy=&endpoint;
        IMemory memory;
        source.mMemoryBases={&memory};
        native_handle_t first{1},second{2},third{3};
        source.recordingFrameHandleCallbackTimestamp(1,&first);
        source.mMemoryBaseAvailableCond.onWait=[&]() {
            source.mStarted=false;
            source.releaseRecordingFrameHandle(&first);
            source.mFramesReceived.clear();
            source.mMemoryBases.push_back(&memory);
        };
        if (batch) source.recordingFrameHandleCallbackTimestampBatch({2,3},{&second,&third});
        else source.recordingFrameHandleCallbackTimestamp(2,&second);
        check(source.mNumFramesReceived==1 && source.mFramesReceived.empty(),
              "stop during memory wait suppresses post-drain enqueue");
        check(source.mPendingRecordingHandles.empty(),"stopped wait releases every registered handle");
        check(endpoint.returned==(batch ? std::vector<int>{1,2,3} : std::vector<int>{1,2}),
              "stop returns pending handles in delivery order");
    }
    return failures ? 1 : 0;
}
"""


class RecordingOrder(unittest.TestCase):
    def test_delivery_order_and_null_memory(self):
        source = (ROOT / "media/libstagefright/CameraSource.cpp").read_text()
        methods = "\n".join(
            function(source, "void CameraSource::" + name + "(")
            for name in [
                "releaseRecordingFrame",
                "releaseRecordingFrameHandle",
                "releaseRecordingFrameHandleBatch",
                "recordingFrameHandleCallbackTimestamp",
                "recordingFrameHandleCallbackTimestampBatch",
                "dataCallbackTimestamp",
            ]
        )
        for name in ("markRecordingFrameReturned", "returnReadyRecordingFrames"):
            signature = "void CameraSource::" + name + "("
            if signature in source:
                methods += function(source, signature)
        output = Path(os.environ["TEST_OUTPUT_DIR"]).resolve(strict=True)
        fixture = output / "recording_handle_order.cpp"
        binary = fixture.with_suffix("")
        fixture.write_text(PREFIX + methods + CASES)
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
        for scenario in ("order", "null"):
            with self.subTest(scenario=scenario):
                subprocess.run([str(binary), scenario], check=True)


if __name__ == "__main__":
    unittest.main()
