from __future__ import annotations

import pytest
from PIL import Image

from viralcut.config import EditConfig
from viralcut.watermark import overlay_position, render_watermark


@pytest.mark.parametrize("style", ["shadow", "pill", "outline", "plain"])
def test_renders_every_style(tmp_path, style):
    cfg = EditConfig(watermark_style=style)
    path = render_watermark(cfg, tmp_path / f"{style}.png")
    img = Image.open(path)
    assert img.mode == "RGBA"
    # Sized for a phone screen: readable, never half the frame.
    assert 0.08 * cfg.width < img.width < 0.65 * cfg.width
    assert img.getbbox() is not None  # something was actually drawn


def test_opacity_is_applied(tmp_path):
    opaque = Image.open(render_watermark(EditConfig(watermark_opacity=1.0), tmp_path / "a.png"))
    faded = Image.open(render_watermark(EditConfig(watermark_opacity=0.4), tmp_path / "b.png"))
    assert max(faded.getchannel("A").getdata()) < max(opaque.getchannel("A").getdata())


def test_scale_changes_size(tmp_path):
    small = Image.open(render_watermark(EditConfig(watermark_scale=1.0), tmp_path / "s.png"))
    big = Image.open(render_watermark(EditConfig(watermark_scale=2.0), tmp_path / "b.png"))
    assert big.width > small.width * 1.5


def test_empty_text_is_an_error(tmp_path):
    with pytest.raises(ValueError):
        render_watermark(EditConfig(watermark_text="   "), tmp_path / "x.png")


def test_custom_image_watermark(tmp_path):
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (400, 200), (255, 0, 0, 255)).save(logo)
    cfg = EditConfig(watermark_image=str(logo))
    out = Image.open(render_watermark(cfg, tmp_path / "wm.png"))
    assert out.width == int(cfg.width * 0.34)


@pytest.mark.parametrize("position,expect_x,expect_y", [
    ("top-left", "54", "86"),
    ("top-right", "W-w-54", "86"),
    ("bottom-left", "54", "H-h-86"),
    ("bottom-right", "W-w-54", "H-h-86"),
])
def test_overlay_positions(position, expect_x, expect_y):
    cfg = EditConfig(watermark_position=position)
    assert overlay_position(cfg) == (expect_x, expect_y)


def test_default_handle_is_branded():
    assert EditConfig().watermark_text == "@Lowk67Tuff"
