"""Exercise legacy priority admission with production service and arbitration code."""

import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(os.environ.get("CAMERA_SOURCE", Path(__file__).resolve().parents[4]))


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth, position = 1, opening + 1
    while depth:
        depth += (source[position] == "{") - (source[position] == "}")
        position += 1
    return source[start:position]


PREFIX = r"""
#include <algorithm>
#include <limits>
#include <cassert>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#define ATRACE_CALL() ((void)0)
#define ALOGE(...) ((void)0)
#define STATUS_ERROR(code, message) ((void)(message), Status{code})
inline constexpr int ERROR_ILLEGAL_ARGUMENT=3, ERROR_PERMISSION_DENIED=1;
inline constexpr int API_1=1, __ANDROID_API_FUTURE__=10000;
inline constexpr int INVALID_ADJ=-10000, UNKNOWN_ADJ=1001;
struct String16 {};
struct String8 {
    String8()=default;
    String8(const String16&) {}
    const char* string() const { return "camera"; }
    template<class... Args> static String8 format(const char*, Args...) { return {}; }
};
struct Status {
    int code=0;
    static Status ok() { return {}; }
    bool isOk() const { return code==0; }
    String8 toString8() const { return {}; }
};
template<class Value> using sp=std::shared_ptr<Value>;
struct ICameraClient {};
struct ICamera { virtual ~ICamera()=default; };
struct Client: ICamera {};
struct CameraThreadState {
    static int getCallingPid() { return 101; }
    static int getCallingUid() { return 1000; }
};
struct CameraService {
    int permissionCalls=0, checkedPid=-1, checkedUid=-1;
    int helperCalls=0, receivedUid=-1, receivedPid=-1, receivedOffset=-1;
    bool permitted=false;
    bool hasPermissionsForSystemCamera(int pid,int uid) {
        ++permissionCalls; checkedPid=pid; checkedUid=uid; return permitted;
    }
    String8 cameraIdIntToStr(int) { return {}; }
    void logRejected(const String8&,int,const String8&,const String8&) {}
    Status validateOomScoreOffset(const String8&,const String16&,int);
    Status connectLegacy(const sp<ICameraClient>&,int,int,const String16&,int,int,sp<ICamera>*);
    Status connectLegacyWithOomScoreOffset(const sp<ICameraClient>&,int,int,
            const String16&,int,int,int,sp<ICamera>*);
    template<class Callback,class ClientType>
    Status connectHelper(const sp<Callback>&,const String8&,int,int,const String16&,
            const std::optional<String16>&,int uid,int pid,int,bool,int offset,int,
            sp<ClientType>& client) {
        ++helperCalls; receivedUid=uid; receivedPid=pid; receivedOffset=offset;
        client=std::make_shared<ClientType>(); return Status::ok();
    }
};
"""
CASES = r"""
int main() {
    CameraService service;
    sp<ICamera> device;
    sp<ICameraClient> callback=std::make_shared<ICameraClient>();
    assert(service.connectLegacy(callback,0,-1,{},777,888,&device).isOk());
    assert(service.receivedOffset==0 && service.permissionCalls==0);
    assert(service.receivedUid==777 && service.receivedPid==888 && device!=nullptr);
    for (int offset : {-1, INT32_MIN}) {
        int before=service.helperCalls;
        assert(service.connectLegacyWithOomScoreOffset(
                callback,0,-1,{},777,888,offset,&device).code==ERROR_ILLEGAL_ARGUMENT);
        assert(service.helperCalls==before && service.permissionCalls==0);
    }
    int before=service.helperCalls;
    assert(service.connectLegacyWithOomScoreOffset(
            callback,0,-1,{},777,888,500,&device).code==ERROR_PERMISSION_DENIED);
    assert(service.helperCalls==before);
    assert(service.checkedPid==101 && service.checkedUid==1000);
    service.permitted=true;
    assert(service.connectLegacyWithOomScoreOffset(
            callback,0,-1,{},777,888,500,&device).isOk());
    assert(service.receivedOffset==500 && service.receivedUid==777 && service.receivedPid==888);
    assert(service.checkedPid==101 && service.checkedUid==1000);
    ClientPriority offsetClient(0,2,false,service.receivedOffset);
    ClientPriority ordinaryClient(100,2,false,0);
    assert(offsetClient>ordinaryClient);
    offsetClient.setScore(10);
    assert(offsetClient.getScore()==510 && offsetClient>ordinaryClient);
    return 0;
}
"""


class LegacyPriorityTest(unittest.TestCase):
    def test_service_permissions_and_arbitration(self):
        source = (
            ROOT / "services/camera/libcameraservice/CameraService.cpp"
        ).read_text()
        methods = "\n".join(
            function(source, signature)
            for signature in (
                "Status CameraService::validateOomScoreOffset(",
                "Status CameraService::connectLegacy(",
                "Status CameraService::connectLegacyWithOomScoreOffset(",
            )
        )
        priority = (
            ROOT / "services/camera/libcameraservice/utils/ClientManager.h"
        ).read_text()
        output = Path(os.environ["TEST_OUTPUT_DIR"]).resolve(strict=True)
        fixture = output / "legacy_priority.cpp"
        fixture.write_text(
            PREFIX
            + function(priority, "class ClientPriority {")
            + ";\n"
            + methods
            + CASES
        )
        executable = output / "legacy_priority"
        subprocess.run(
            [
                os.environ.get("CXX", "c++"),
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-fsanitize=undefined",
                "-fno-sanitize-recover=all",
                str(fixture),
                "-o",
                str(executable),
            ],
            check=True,
        )
        subprocess.run([str(executable)], check=True)

    def test_score_offsets_saturate_without_priority_inversion(self):
        priority = (
            ROOT / "services/camera/libcameraservice/utils/ClientManager.h"
        ).read_text()
        output = Path(os.environ["TEST_OUTPUT_DIR"]).resolve(strict=True)
        fixture = output / "priority_score_bounds.cpp"
        fixture.write_text(
            "#include <algorithm>\n#include <limits>\n"
            + PREFIX
            + function(priority, "class ClientPriority {")
            + ";\n"
            + r"""
int main() {
    ClientPriority maximum(100,2,false,INT32_MAX);
    assert(maximum.getScore()==INT32_MAX);
    maximum.setScore(999);
    assert(maximum.getScore()==INT32_MAX);
    maximum.setScore(INVALID_ADJ);
    assert(maximum.getScore()==UNKNOWN_ADJ);
    maximum.setScore(-1000);
    assert(maximum.getScore()==INT32_MAX-1000);
    ClientPriority negative(INT32_MIN,2,false,-1);
    assert(negative.getScore()==INT32_MIN);
    ClientPriority ordinary(100,2,false,17);
    assert(ordinary.getScore()==117);
    ordinary.setScore(200);
    assert(ordinary.getScore()==217);
    for (int score : {-1000,0,100,999}) {
        int previous=INT32_MIN;
        for (int offset : {0,1,500,INT32_MAX-1,INT32_MAX}) {
            ClientPriority priority(score,2,false,offset);
            assert(priority.getScore()>=previous);
            previous=priority.getScore();
        }
    }
    return 0;
}
"""
        )
        executable = output / "priority_score_bounds"
        subprocess.run(
            [
                os.environ.get("CXX", "c++"),
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-fsanitize=undefined",
                "-fno-sanitize-recover=all",
                str(fixture),
                "-o",
                str(executable),
            ],
            check=True,
        )
        subprocess.run([str(executable)], check=True)

    def test_hal3_and_legacy_share_validation(self):
        source = (
            ROOT / "services/camera/libcameraservice/CameraService.cpp"
        ).read_text()
        for signature in (
            "Status CameraService::connectDevice(",
            "Status CameraService::connectLegacyWithOomScoreOffset(",
        ):
            method = function(source, signature)
            self.assertLess(
                method.index("validateOomScoreOffset("), method.index("connectHelper<")
            )
            self.assertIn("if (!ret.isOk()) return ret;", method)


if __name__ == "__main__":
    unittest.main()
