#!/usr/bin/env python3
"""Generate a synthetic test clip (no third-party media required).

Used by the test-suite and for eyeballing the pipeline:

    python scripts/make_test_clip.py --preset landscape -o work/test_16x9.mp4
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from viralcut.ffmpeg_tool import find_ffmpeg  # noqa: E402

PRESETS = {
    "landscape": ("1920x1080", 30),
    "portrait": ("1080x1920", 30),
    "square": ("1080x1080", 30),
    "tall": ("1080x2340", 30),
    "sd": ("640x480", 25),
    "cinema": ("2560x1080", 24),
}


def make_clip(out: Path, size: str, fps: int, duration: float, audio: bool = True) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    args = [
        find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}:duration={duration}",
    ]
    if audio:
        args += ["-f", "lavfi", "-i",
                 f"sine=frequency=440:sample_rate=48000:duration={duration}"]
    args += [
        "-filter_complex",
        "[0:v]drawbox=x=0:y=0:w=iw:h=ih:color=black@0.0:t=1,"
        "hue=h='mod(t*40,360)':s=1.1[v]",
        "-map", "[v]",
    ]
    if audio:
        args += ["-map", "1:a", "-c:a", "aac", "-b:a", "192k"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-r", str(fps), str(out)]
    subprocess.run(args, check=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preset", default="landscape", choices=sorted(PRESETS))
    ap.add_argument("--size", default=None, help="explicit WxH (overrides preset)")
    ap.add_argument("--fps", type=int, default=None)
    ap.add_argument("--duration", type=float, default=6.0)
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    size, fps = PRESETS[args.preset]
    size = args.size or size
    fps = args.fps or fps
    out = Path(args.output or f"work/test_{args.preset}.mp4")
    make_clip(out, size, fps, args.duration, audio=not args.no_audio)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
