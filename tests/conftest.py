"""Shared fixtures. Every asset used by the suite is synthesised locally —
the repository never needs (and never contains) sample media."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.make_test_clip import make_clip  # noqa: E402
from viralcut.ffmpeg_tool import FFmpegNotFound, find_ffmpeg  # noqa: E402


def _ffmpeg_available() -> bool:
    try:
        find_ffmpeg()
        return True
    except FFmpegNotFound:
        return False


requires_ffmpeg = pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg is not installed")


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("media")


@pytest.fixture(scope="session")
def landscape_clip(media_dir: Path) -> Path:
    return make_clip(media_dir / "landscape.mp4", "640x360", 30, 2.0, audio=True)


@pytest.fixture(scope="session")
def portrait_clip(media_dir: Path) -> Path:
    return make_clip(media_dir / "portrait.mp4", "360x640", 30, 2.0, audio=True)


@pytest.fixture(scope="session")
def silent_clip(media_dir: Path) -> Path:
    return make_clip(media_dir / "silent.mp4", "480x480", 25, 2.0, audio=False)


@pytest.fixture(scope="session")
def flat_clip(media_dir: Path) -> Path:
    """A static, flat-grey clip.

    Every frame is identical, so two timestamps from the *same* render can be
    compared directly. That isolates an overlay perfectly: no moving pattern,
    and no second encode whose colour round-trip would muddy the difference.
    """
    out = media_dir / "flat.mp4"
    if out.exists():
        return out
    subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=0x303030:s=360x640:r=30:d=2.0",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
         "-t", "2.0", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", "-y", str(out)],
        check=True, capture_output=True,
    )
    return out
