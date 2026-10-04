from __future__ import annotations

import pytest

from viralcut.config import EditConfig
from viralcut.framing import build_framing, framing_report, resolve_fill
from viralcut.probe import MediaInfo


def info(w: int, h: int) -> MediaInfo:
    return MediaInfo(path="x.mp4", width=w, height=h, fps=30, duration=10, has_audio=True)


@pytest.mark.parametrize("w,h,expected", [
    (1080, 1920, "crop"),    # already 9:16
    (1080, 2340, "crop"),    # taller than target
    (1080, 1350, "crop"),    # 4:5 — close enough, crop keeps it full-bleed
    (1920, 1080, "smart"),   # 16:9 — never cut 60 % of the frame away
    (2560, 1080, "smart"),   # ultrawide
    (1080, 1080, "smart"),   # square — a full-bleed crop would bin 44 %
])
def test_auto_strategy(w, h, expected):
    cfg = EditConfig(fill="auto")
    assert resolve_fill(info(w, h), cfg, cfg.width / cfg.height) == expected


def test_explicit_mode_is_respected():
    cfg = EditConfig(fill="blur")
    assert resolve_fill(info(1080, 1920), cfg, 0.5625) == "blur"


def test_crop_graph_targets_the_canvas_and_honours_focus():
    cfg = EditConfig(fill="crop", focus_x=0.25, focus_y=0.1)
    segments, mode = build_framing(info(1920, 1080), cfg, 1080, 1920, "0:v", "out")
    graph = ";".join(segments)
    assert mode == "crop"
    assert "scale=1080:1920:force_original_aspect_ratio=increase" in graph
    assert "crop=1080:1920:(iw-ow)*0.2500:(ih-oh)*0.1000" in graph
    assert graph.endswith("[out]")


def test_blur_graph_builds_background_and_foreground():
    cfg = EditConfig(fill="blur")
    segments, mode = build_framing(info(1920, 1080), cfg, 1080, 1920, "0:v", "out")
    graph = ";".join(segments)
    assert mode == "blur"
    assert "split=2[bgsrc][fgsrc]" in graph
    assert "gblur" in graph
    assert "force_original_aspect_ratio=decrease" in graph   # nothing cropped off
    assert "overlay=x=(W-w)/2:y=(H-h)/2" in graph


def test_smart_pre_crops_only_very_wide_sources():
    cfg = EditConfig(fill="smart")
    wide = ";".join(build_framing(info(2560, 1080), cfg, 1080, 1920, "0:v", "out")[0])
    narrow = ";".join(build_framing(info(1280, 1024), cfg, 1080, 1920, "0:v", "out")[0])
    assert "crop=ih*1.3000" in wide
    assert "crop=ih*" not in narrow


def test_fit_pads_with_configured_colour():
    cfg = EditConfig(fill="fit", pad_color="white")
    graph = ";".join(build_framing(info(1920, 1080), cfg, 1080, 1920, "0:v", "out")[0])
    assert "pad=1080:1920" in graph and "color=white" in graph


def test_every_mode_declares_square_pixels():
    for mode in ("crop", "blur", "fit", "smart"):
        cfg = EditConfig(fill=mode)
        graph = ";".join(build_framing(info(1920, 1080), cfg, 1080, 1920, "0:v", "out")[0])
        assert "setsar=1" in graph


def test_report_is_human_readable():
    cfg = EditConfig()
    text = framing_report(info(1920, 1080), cfg, "smart")
    assert "1920x1080" in text and "1080x1920" in text
