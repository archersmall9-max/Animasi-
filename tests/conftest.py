"""Shared fixtures. Every asset used by the suite is synthesised locally —
the repository never needs (and never contains) sample media."""

from __future__ import annotations

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
