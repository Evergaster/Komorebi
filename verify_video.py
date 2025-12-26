import sys
import os
import subprocess


def verify(path):
    print(f"Verifying: {path}")
    if not os.path.exists(path):
        print("FILE DOES NOT EXIST")
        return

    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,width,height",
                "-of",
                "default=noprint_wrappers=1",
                path,
            ],
            stderr=subprocess.STDOUT,
            text=True,
        )
        if out.strip():
            print("SUCCESS:")
            print(out.strip())
        else:
            print("FAILED: ffprobe returned empty output")
    except FileNotFoundError:
        print("FAILED: ffprobe not found (install ffmpeg)")
    except subprocess.CalledProcessError as e:
        print("FAILED: ffprobe error")
        print(e.output)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        verify(sys.argv[1])
    else:
        print("Usage: python verify_video.py <path>")
