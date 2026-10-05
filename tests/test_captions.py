"""Captions: parsing, layout, emoji handling and placement."""

from __future__ import annotations

import pytest
from PIL import Image

from viralcut.captions import (
    Caption,
    caption_overlay_xy,
    is_emoji,
    parse_captions,
    render_caption,
    resolve_emoji_font,
    validate_captions,
)
from viralcut.config import EditConfig


def test_emoji_detection_covers_the_ranges_we_use():
    for ch in "👀🧡😐🍦💀🔥😂":
        assert is_emoji(ch), ch
    for ch in "abcXYZ123.,!?'-…":
        assert not is_emoji(ch), ch
    # Joiners and variation selectors must not be treated as glyphs.
    assert not is_emoji("\ufe0f")
    assert not is_emoji("\u200d")


def test_parse_sorts_by_start_and_rejects_junk():
    caps = parse_captions([
        {"text": "second", "start": 5.0, "end": 6.0},
        {"text": "first", "start": 1.0, "end": 2.0},
    ])
    assert [c.text for c in caps] == ["first", "second"]

    with pytest.raises(ValueError, match="unknown key"):
        parse_captions([{"text": "x", "start": 0, "end": 1, "colour": "red"}])
    with pytest.raises(ValueError, match="must be after"):
        parse_captions([{"text": "x", "start": 2.0, "end": 1.0}])
    with pytest.raises(ValueError, match="position"):
        parse_captions([{"text": "x", "start": 0, "end": 1, "position": "sideways"}])


def test_parse_accepts_a_wrapper_object_and_a_bare_list():
    payload = {"captions": [{"text": "hi", "start": 0, "end": 1}]}
    assert len(parse_captions(payload)) == 1
    assert len(parse_captions(payload["captions"])) == 1
    assert parse_captions(None) == []


def test_validate_flags_overruns_flashes_and_overlaps():
    caps = parse_captions([
        {"text": "way too quick", "start": 0.0, "end": 0.3},
        {"text": "overlapping", "start": 0.2, "end": 9.0},
        {"text": "past the end", "start": 9.0, "end": 30.0},
    ])
    notes = " | ".join(validate_captions(caps, total_duration=15.0))
    assert "too quick" in notes
    assert "stacked" in notes
    assert "only 15.00s long" in notes
    assert validate_captions(parse_captions([{"text": "fine", "start": 1, "end": 4}]), 15.0) == []


def test_render_produces_a_transparent_png_with_visible_ink(tmp_path):
    cfg = EditConfig()
    cap = Caption(text="one lick. that's the whole review", start=1.0, end=4.0)
    path, w, h = render_caption(cfg, cap, tmp_path / "cap.png")

    img = Image.open(path)
    assert img.mode == "RGBA"
    assert (img.width, img.height) == (w, h)
    assert w <= cfg.width, "caption must never be wider than the canvas"

    alpha = img.getchannel("A")
    assert alpha.getextrema()[1] == 255, "some pixels must be fully opaque"
    opaque = sum(1 for v in alpha.getdata() if v > 200)
    assert 0.02 < opaque / (w * h) < 0.65, "ink coverage looks wrong"


def test_long_text_wraps_instead_of_overflowing(tmp_path):
    cfg = EditConfig()
    short = render_caption(cfg, Caption(text="short", start=0, end=1), tmp_path / "a.png")
    long = render_caption(
        cfg,
        Caption(
            text="a tumour took them and he hears just fine which is the part "
                 "people always want to know about",
            start=0, end=1,
        ),
        tmp_path / "b.png",
    )
    assert long[2] > short[2], "wrapped text should be taller"
    assert long[1] <= cfg.width * cfg.caption_max_width + 80


@pytest.mark.skipif(resolve_emoji_font() is None, reason="no colour-emoji font installed")
def test_emoji_render_in_colour(tmp_path):
    cfg = EditConfig()
    plain, pw, _ = render_caption(cfg, Caption(text="round two", start=0, end=1),
                                  tmp_path / "plain.png")
    withemoji, ew, _ = render_caption(cfg, Caption(text="round two 🍦", start=0, end=1),
                                      tmp_path / "emoji.png")
    assert ew > pw, "the emoji must take horizontal space"

    img = Image.open(withemoji).convert("RGBA")
    hues = {
        px[:3] for px in img.getdata()
        if px[3] > 200 and max(px[:3]) - min(px[:3]) > 40
    }
    assert hues, "emoji should contribute saturated colour, not just black and white"


def test_text_survives_without_an_emoji_font(tmp_path, monkeypatch):
    # A machine with no colour-emoji font must still produce readable text.
    monkeypatch.setattr("viralcut.captions.resolve_emoji_font", lambda *_a, **_k: None)
    cfg = EditConfig()
    path, w, h = render_caption(cfg, Caption(text="no font here 🍦", start=0, end=1),
                                tmp_path / "c.png")
    assert w > 0 and h > 0
    assert Image.open(path).getchannel("A").getextrema()[1] == 255


def test_placement_is_centred_and_stays_inside_the_canvas():
    cfg = EditConfig()
    for position in ("top", "upper", "center", "lower", "bottom"):
        cap = Caption(text="x", start=0, end=1, position=position)
        x, y = caption_overlay_xy(cfg, cap, 600, 200)
        assert x == (cfg.width - 600) // 2
        assert 0 <= y <= cfg.height - 200

    # A caption anchored off the bottom edge is pulled back inside.
    cap = Caption(text="x", start=0, end=1, position="0.99")
    _, y = caption_overlay_xy(cfg, cap, 600, 400)
    assert y + 400 <= cfg.height


def test_lower_default_clears_the_player_chrome():
    cfg = EditConfig()
    cap = Caption(text="x", start=0, end=1)          # default position
    _, y = caption_overlay_xy(cfg, cap, 900, 240)
    assert (y + 240) / cfg.height < 0.82, "captions must sit above the platform UI band"
