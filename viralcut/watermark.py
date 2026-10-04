"""Watermark rendering.

The watermark is rasterised once with Pillow (supersampled, then resampled
down) instead of being drawn by FFmpeg's ``drawtext``. That means:

* identical output on every machine, no font-config surprises;
* real drop shadows / outlines / pill backgrounds;
* sub-pixel-clean edges at any size;
* it is composited last, so it is never blurred by the intro/outro.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import EditConfig

log = logging.getLogger("viralcut.watermark")

SUPERSAMPLE = 3

# Bundled first, then the usual suspects on macOS / Windows / Linux.
_FONT_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "assets" / "fonts" / "VC-Brand-Bold.ttf",
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    Path("/System/Library/Fonts/HelveticaNeue.ttc"),
    Path("C:/Windows/Fonts/segoeuib.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
)


def resolve_font(explicit: str | None = None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return p
        raise FileNotFoundError(f"Watermark font not found: {p}")
    for candidate in _FONT_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _load_font(size: int, explicit: str | None = None) -> ImageFont.FreeTypeFont:
    path = resolve_font(explicit)
    if path is None:  # pragma: no cover - only on a font-less system
        log.warning("No TrueType font found; falling back to Pillow's bitmap font.")
        return ImageFont.load_default()
    return ImageFont.truetype(str(path), size)


def _draw_tracked_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    tracking: float,
    stroke_width: int = 0,
    stroke_fill: tuple[int, int, int, int] | None = None,
) -> None:
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill,
                  stroke_width=stroke_width, stroke_fill=stroke_fill)
        x += draw.textlength(char, font=font) + tracking


def _text_size(font: ImageFont.FreeTypeFont, text: str, tracking: float) -> tuple[int, int]:
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    width = sum(probe.textlength(c, font=font) for c in text) + tracking * max(0, len(text) - 1)
    ascent, descent = font.getmetrics() if hasattr(font, "getmetrics") else (font.size, 0)
    return int(round(width)), int(round(ascent + descent))


def render_watermark(cfg: EditConfig, out_path: str | Path, font_path: str | None = None) -> Path:
    """Render the watermark PNG (RGBA) and return its path."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if cfg.watermark_image:
        src = Path(cfg.watermark_image).expanduser()
        if not src.exists():
            raise FileNotFoundError(f"Watermark image not found: {src}")
        img = Image.open(src).convert("RGBA")
        target_w = int(cfg.width * 0.34 * cfg.watermark_scale)
        if img.width != target_w:
            ratio = target_w / img.width
            img = img.resize((target_w, max(1, int(img.height * ratio))), Image.LANCZOS)
        img = _apply_opacity(img, cfg.watermark_opacity)
        img.save(out)
        return out

    text = cfg.watermark_text or ""
    if not text.strip():
        raise ValueError("watermark_text is empty — nothing to render")

    ss = SUPERSAMPLE
    # ~2.35 % of canvas height: readable on a phone, never obnoxious.
    font_px = max(12, int(round(cfg.height * 0.0235 * cfg.watermark_scale)))
    font = _load_font(font_px * ss, font_path)
    tracking = font_px * ss * 0.018

    text_w, text_h = _text_size(font, text, tracking)
    style = cfg.watermark_style

    pad_x = int(font_px * ss * (0.62 if style == "pill" else 0.30))
    pad_y = int(font_px * ss * (0.38 if style == "pill" else 0.30))
    canvas_w = text_w + pad_x * 2
    canvas_h = text_h + pad_y * 2

    layer = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    if style == "pill":
        pill = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        ImageDraw.Draw(pill).rounded_rectangle(
            (0, 0, canvas_w - 1, canvas_h - 1),
            radius=canvas_h // 2,
            fill=(0, 0, 0, 105),
        )
        layer = Image.alpha_composite(layer, pill)

    if style == "shadow":
        shadow = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        _draw_tracked_text(
            ImageDraw.Draw(shadow),
            (pad_x, pad_y + int(font_px * ss * 0.07)),
            text, font, (0, 0, 0, 190), tracking,
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=font_px * ss * 0.09))
        layer = Image.alpha_composite(layer, shadow)

    text_layer = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    stroke = int(font_px * ss * 0.085) if style == "outline" else 0
    _draw_tracked_text(
        ImageDraw.Draw(text_layer),
        (pad_x, pad_y),
        text, font, (255, 255, 255, 255), tracking,
        stroke_width=stroke,
        stroke_fill=(0, 0, 0, 215) if stroke else None,
    )
    layer = Image.alpha_composite(layer, text_layer)

    final_size = (max(2, canvas_w // ss), max(2, canvas_h // ss))
    layer = layer.resize(final_size, Image.LANCZOS)
    layer = _apply_opacity(layer, cfg.watermark_opacity)
    layer.save(out)
    log.info("watermark: %s (%dx%d) style=%s", text, layer.width, layer.height, style)
    return out


def _apply_opacity(img: Image.Image, opacity: float) -> Image.Image:
    if opacity >= 0.999:
        return img
    alpha = img.getchannel("A").point(lambda a: int(a * max(0.0, min(1.0, opacity))))
    img.putalpha(alpha)
    return img


def overlay_position(cfg: EditConfig) -> tuple[str, str]:
    """Return ``(x_expr, y_expr)`` for FFmpeg's overlay filter."""
    mx = int(round(cfg.width * cfg.watermark_margin_x))
    my = int(round(cfg.height * cfg.watermark_margin_y))
    pos = cfg.watermark_position
    x = f"{mx}" if pos.endswith("left") else f"W-w-{mx}"
    y = f"{my}" if pos.startswith("top") else f"H-h-{my}"
    return x, y
