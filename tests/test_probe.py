from __future__ import annotations

import pytest
from conftest import requires_ffmpeg  # noqa: F401

from viralcut.probe import MediaInfo, probe


def test_aspect_and_orientation_helpers():
    assert MediaInfo("x", 1920, 1080, 30, 10, True).orientation == "landscape"
    assert MediaInfo("x", 1080, 1920, 30, 10, True).orientation == "portrait"
    assert MediaInfo("x", 1080, 1080, 30, 10, True).orientation == "square"
    assert MediaInfo("x", 1080, 1920, 30, 10, True).aspect == pytest.approx(0.5625, abs=1e-4)


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        probe("definitely/not/here.mp4")


@requires_ffmpeg
def test_probe_reads_a_real_clip(landscape_clip):
    info = probe(landscape_clip)
    assert (info.width, info.height) == (640, 360)
    assert info.fps == pytest.approx(30, abs=0.5)
    assert info.duration == pytest.approx(2.0, abs=0.2)
    assert info.has_audio is True
    assert "640x360" in info.summary()


@requires_ffmpeg
def test_probe_detects_missing_audio(silent_clip):
    assert probe(silent_clip).has_audio is False
