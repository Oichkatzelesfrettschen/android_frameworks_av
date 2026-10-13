"""Exercise the default CameraSource factory with production mode negotiation."""

import os
from pathlib import Path
import subprocess
import unittest

CHECKOUT = Path(__file__).resolve().parents[4]


def function(source, signature):
    start = source.index(signature)
    position = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[position] == "{") - (source[position] == "}")
        position += 1
    return source[start:position]


class SourceModeTest(unittest.TestCase):
    def test_factory_negotiates_queue_metadata_and_legacy_yuv(self):
        checkout = Path(os.environ.get("CAMERA_SOURCE_CHECKOUT", CHECKOUT))
        source = (checkout / "media/libstagefright/CameraSource.cpp").read_text()
        factory = function(source, "CameraSource *CameraSource::Create(")
        start = source.index(
            "    mVideoBufferMode = hardware::ICamera::VIDEO_BUFFER_MODE_DATA_CALLBACK_YUV;"
        )
        end = source.index("    int64_t glitchDurationUs", start)
        negotiation = source[start:end]
        prefix = r"""
#include <cassert>
#include <cstddef>
#define ALOGE(...) ((void)0)
using status_t = int;
using String16 = int;
constexpr int OK = 0;
namespace hardware { struct ICamera {
    enum { VIDEO_BUFFER_MODE_BUFFER_QUEUE=1, VIDEO_BUFFER_MODE_DATA_CALLBACK_METADATA=2,
           VIDEO_BUFFER_MODE_DATA_CALLBACK_YUV=3 };
}; }
template<class T> struct sp {};
struct Size { int width, height; };
struct Camera { enum { USE_CALLING_UID=-1, USE_CALLING_PID=-1 }; };
static int supportedMode;
static int destroyed;
struct Device {
    int setVideoBufferMode(int mode) { return mode==supportedMode ? OK : -1; }
};
struct CameraSource {
    Device device;
    Device* mCamera=&device;
    int mVideoBufferMode=0;
    int status;
    static CameraSource* Create(const String16&);
    CameraSource(const sp<hardware::ICamera>&,void*,int,const String16&,int,int,
                 Size,int,void*,bool metadata):status(configure(metadata)) {}
    ~CameraSource() { ++destroyed; }
    int initCheck() { return status; }
    int configure(bool storeMetaDataInVideoBuffers) {
        int err=OK;
"""
        suffix = r"""
        return OK;
    }
};
"""
        cases = r"""
int main() {
    for (int mode : {1,2,3}) {
        supportedMode=mode;
        CameraSource* source=CameraSource::Create(0);
        assert(source!=nullptr && source->mVideoBufferMode==mode);
        delete source;
    }
    assert(destroyed==3);
    supportedMode=0;
    assert(CameraSource::Create(0)==nullptr && destroyed==4);
}
"""
        output = Path(os.environ["TEST_OUTPUT_DIR"]).resolve(strict=True)
        fixture = output / "camera_source_mode.cpp"
        fixture.write_text(
            "#include <initializer_list>\n"
            + prefix
            + negotiation
            + suffix
            + factory
            + cases
        )
        binary = output / "camera_source_mode"
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
