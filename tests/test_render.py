"""End-to-end renders against locally generated clips.

Everything is rendered small and fast (360x640 @ 30 fps, ultrafast) — the
goal is to prove the graph is correct, not to benchmark the encoder.
"""

from __future__ import annotations

import json

import pytest
from conftest import requires_ffmpeg  # noqa: F401  (fixture module on sys.path)

from viralcut.config import build_config
from viralcut.probe import probe
from viralcut.render import _plan_timing, _zoom_bounds, render


def fast_config(**overrides):
    cfg = build_config("shorts", **overrides)
    cfg.width, cfg.height, cfg.fps = 360, 640, 30
    cfg.crf, cfg.x264_preset = 30, "ultrafast"
    cfg.max_bitrate, cfg.bufsize = "8M", "16M"
    cfg.loudnorm_passes = 1
    return cfg


@requires_ffmpeg
def test_landscape_becomes_vertical_with_intro_and_outro(landscape_clip, tmp_path):
    cfg = fast_config()
    out = tmp_path / "vertical.mp4"
    result = render(landscape_clip, out, cfg)

    assert out.exists()
    assert (result.width, result.height) == (360, 640)
    assert result.fps == 30
    # 2 s body + intro + outro
    assert result.duration == pytest.approx(2.0 + cfg.intro_duration + cfg.outro_duration, abs=0.2)
    assert result.fill_mode == "smart"


@requires_ffmpeg
def test_report_sidecar_is_written(landscape_clip, tmp_path):
    out = tmp_path / "report.mp4"
    render(landscape_clip, out, fast_config())
    sidecar = out.with_suffix(out.suffix + ".report.json")
    data = json.loads(sidecar.read_text())
    assert data["config"]["watermark_text"] == "@Lowk67Tuff"
    assert data["timeline"]["total"] > data["timeline"]["body"]
    assert data["output"]["width"] == 360


@requires_ffmpeg
def test_portrait_source_is_cropped_not_padded(portrait_clip, tmp_path):
    result = render(portrait_clip, tmp_path / "p.mp4", fast_config())
    assert result.fill_mode == "crop"


@requires_ffmpeg
def test_silent_source_still_gets_an_audio_track(silent_clip, tmp_path):
    out = tmp_path / "silent.mp4"
    render(silent_clip, out, fast_config())
    assert probe(out).has_audio


@requires_ffmpeg
def test_trim_and_speed_shorten_the_body(landscape_clip, tmp_path):
    cfg = fast_config(start=0.5, end=1.5, speed=2.0)
    result = render(landscape_clip, tmp_path / "trim.mp4", cfg)
    expected = 0.5 + cfg.intro_duration + cfg.outro_duration
    assert result.duration == pytest.approx(expected, abs=0.2)


@requires_ffmpeg
def test_no_intro_no_outro_matches_source_duration(landscape_clip, tmp_path):
    cfg = fast_config(intro="none", outro="none")
    result = render(landscape_clip, tmp_path / "bare.mp4", cfg)
    assert result.duration == pytest.approx(2.0, abs=0.15)


@requires_ffmpeg
def test_watermark_is_actually_burned_in(portrait_clip, tmp_path):
    """Compare a watermarked render against an identical clean one."""
    import subprocess

    from PIL import Image, ImageChops

    from viralcut.ffmpeg_tool import find_ffmpeg

    marked = tmp_path / "marked.mp4"
    clean = tmp_path / "clean.mp4"
    cfg = fast_config(intro="none", outro="none", zoom="off", grade="none")
    render(portrait_clip, marked, cfg)
    cfg2 = fast_config(intro="none", outro="none", zoom="off", grade="none")
    cfg2.watermark_text = ""
    render(portrait_clip, clean, cfg2)

    frames = []
    for src in (marked, clean):
        png = tmp_path / f"{src.stem}.png"
        subprocess.run([find_ffmpeg(), "-y", "-loglevel", "error", "-ss", "0.5", "-i", str(src),
                        "-frames:v", "1", "-update", "1", str(png)], check=True)
        frames.append(Image.open(png).convert("L"))
    diff = ImageChops.difference(*frames)
    box = diff.getbbox()
    assert box is not None, "watermark made no difference to the frame"
    # ...and the difference sits in the top-left corner.
    assert box[0] < 0.5 * frames[0].width
    assert box[1] < 0.35 * frames[0].height


def test_max_duration_budgets_the_whole_delivery():
    from viralcut.probe import MediaInfo

    cfg = build_config("shorts", max_duration=10.0)
    info = MediaInfo(path="x", width=1920, height=1080, fps=30, duration=60, has_audio=True)
    _, _, body = _plan_timing(info, cfg)
    assert body + cfg.intro_duration + cfg.outro_duration == pytest.approx(10.0, abs=0.01)


def test_zoom_bounds_are_symmetric():
    assert _zoom_bounds(build_config("shorts", zoom="off")) == (1.0, 1.0, 1.0)
    scale, start, end = _zoom_bounds(build_config("shorts", zoom="push", zoom_amount=0.1))
    assert (scale, start, end) == (1.1, 1.0, 1.1)
    scale, start, end = _zoom_bounds(build_config("shorts", zoom="hook", zoom_amount=0.1))
    assert (scale, start, end) == (1.1, 1.1, 1.0)




def _band_ink(path, t):
    """Mean brightness of the strip captions are drawn into.

    White text on the flat grey backdrop raises this; nothing else in the
    frame moves, so any change is the caption. -ss goes after -i so the
    seek is frame-accurate rather than snapping to a keyframe.
    """
    import subprocess

    from viralcut.ffmpeg_tool import find_ffmpeg

    raw = subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error",
         "-i", str(path), "-ss", f"{t}", "-frames:v", "1",
         "-vf", "crop=iw:ih*0.16:0:ih*0.62,format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout
    assert raw, f"no frame at t={t}"
    return sum(raw) / len(raw)


def _caption_config(captions):
    cfg = fast_config()
    cfg.intro, cfg.outro = "none", "none"
    cfg.watermark_text = ""
    cfg.zoom = "off"
    cfg.captions = captions
    return cfg


@requires_ffmpeg
def test_captions_appear_only_inside_their_window(flat_clip, tmp_path):
    """A hard-cut caption must be on screen for its window and absent outside
    it. The source is static, so two timestamps of one render differ only by
    what the overlay drew."""
    out = tmp_path / "captioned.mp4"
    render(flat_clip, out,
           _caption_config([{"text": "HELLO", "start": 0.70, "end": 1.30, "fade": 0.0}]))

    before, during, after = _band_ink(out, 0.30), _band_ink(out, 1.00), _band_ink(out, 1.70)

    assert during > before + 2.0, f"caption never reached the picture ({before:.2f} -> {during:.2f})"
    assert abs(after - before) < 0.4, f"caption left a trace behind it ({before:.2f} vs {after:.2f})"


@requires_ffmpeg
def test_faded_captions_ramp_rather_than_pop(flat_clip, tmp_path):
    """With a fade set, the caption should be part-way up mid-ramp."""
    out = tmp_path / "faded.mp4"
    render(flat_clip, out,
           _caption_config([{"text": "HELLO", "start": 0.50, "end": 1.80, "fade": 0.40}]))

    off = _band_ink(out, 0.20)
    mid = _band_ink(out, 0.70)
    full = _band_ink(out, 1.20)

    assert off < mid < full, f"expected a ramp, got off={off:.2f} mid={mid:.2f} full={full:.2f}"
    assert full - off > 2.0, "caption never reached full strength"
