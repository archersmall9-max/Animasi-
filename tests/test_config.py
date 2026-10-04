from __future__ import annotations

import json

import pytest

from viralcut.config import PRESETS, EditConfig, build_config


def test_default_is_vertical_1080p60():
    cfg = EditConfig()
    assert (cfg.width, cfg.height, cfg.fps) == (1080, 1920, 60)
    assert cfg.watermark_text == "@Lowk67Tuff"
    assert cfg.watermark_position == "top-left"


@pytest.mark.parametrize(
    "ratio,expected",
    [("9:16", (1080, 1920)), ("1:1", (1080, 1080)), ("16:9", (1920, 1080)), ("4:5", (1080, 1350))],
)
def test_known_ratios(ratio, expected):
    cfg = EditConfig(ratio=ratio)
    assert (cfg.width, cfg.height) == expected


def test_custom_ratio_is_even_and_portrait_locks_long_edge():
    cfg = EditConfig(ratio="3:4")
    assert cfg.height == 1920
    assert cfg.width % 2 == 0
    assert abs(cfg.width / cfg.height - 0.75) < 0.01


@pytest.mark.parametrize("field,value", [
    ("fill", "nope"), ("zoom", "nope"), ("grade", "nope"),
    ("intro", "nope"), ("outro", "nope"), ("watermark_style", "nope"),
    ("watermark_position", "middle"), ("speed", 99.0), ("watermark_opacity", 5.0),
])
def test_invalid_values_rejected(field, value):
    with pytest.raises(ValueError):
        EditConfig(**{field: value})


def test_every_preset_builds_and_is_60fps():
    for name in PRESETS:
        cfg = build_config(name)
        assert cfg.fps == 60
        assert cfg.notes["preset"] == name


def test_overrides_win_and_none_is_ignored():
    cfg = build_config("tiktok", grade="cinematic", crf=None)
    assert cfg.grade == "cinematic"
    assert cfg.crf == PRESETS["tiktok"]["crf"]


def test_roundtrip(tmp_path):
    cfg = build_config("shorts", zoom="hook", watermark_text="@Lowk67Tuff")
    path = tmp_path / "cfg.json"
    cfg.save(path)
    again = EditConfig.load(path)
    assert again.to_dict() == cfg.to_dict()
    assert json.loads(path.read_text())["watermark_text"] == "@Lowk67Tuff"


def test_unknown_key_is_rejected():
    with pytest.raises(ValueError):
        EditConfig.from_dict({"nonsense": 1})
