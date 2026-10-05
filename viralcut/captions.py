"""Timed on-screen captions, rendered with Pillow and overlaid by ffmpeg.

The portable ffmpeg build this project targets has no ``drawtext`` filter, so
every glyph is drawn here and handed to ffmpeg as an RGBA image.  That turns
out to be an advantage: it is the only practical way to mix a text typeface
with a colour-emoji font on one line, which ``drawtext`` cannot do at all.

Two fonts are in play.

* The text face (DejaVu Sans Bold by default) draws at whatever pixel size the
  layout asks for.
* Noto Color Emoji is a CBDT bitmap font with a single 109 px strike.  Pillow
  will only rasterise it at that exact size, so each emoji is drawn at 109 px
  into its own image and resampled down to sit on the text baseline.

If no colour-emoji font is installed the captions still render - the emoji are
simply dropped rather than turning into tofu boxes, which looks deliberate
instead of broken.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import EditConfig
from .watermark import resolve_font

log = logging.getLogger("viralcut.captions")

#: The one size Noto Color Emoji's bitmap strike can be rasterised at.
EMOJI_STRIKE = 109

CAPTION_POSITIONS = ("top", "upper", "center", "lower", "bottom")

#: Vertical anchor of the caption block, as a fraction of canvas height.
#: "lower" is the house default: clear of the subject's face and clear of the
#: player chrome that platforms paint over the bottom ~18%.
_POSITION_Y = {
    "top": 0.085,
    "upper": 0.20,
    "center": 0.50,
    "lower": 0.70,
    "bottom": 0.78,
}

_EMOJI_FONT_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "assets" / "fonts" / "NotoColorEmoji.ttf",
    Path.home() / "fonts" / "NotoColorEmoji.ttf",
    Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
    Path("/usr/share/fonts/truetype/noto-color-emoji/NotoColorEmoji.ttf"),
    Path("/usr/share/fonts/noto/NotoColorEmoji.ttf"),
    Path("/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf"),
    Path("/System/Library/Fonts/Apple Color Emoji.ttc"),
)

# Variation selector-16 and the zero-width joiner only matter to a shaping
# engine; without one they would render as stray boxes.
_INVISIBLE = {"\ufe0f", "\ufe0e", "\u200d"}


def resolve_emoji_font(explicit: str | None = None) -> Path | None:
    """Locate a colour-emoji font, or return None if the system has none."""
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"Emoji font not found: {p}")
        return p
    for candidate in _EMOJI_FONT_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def is_emoji(ch: str) -> bool:
    """True for characters a colour-emoji font is expected to carry."""
    if ch in _INVISIBLE:
        return False
    cp = ord(ch)
    return (
        0x1F300 <= cp <= 0x1FAFF      # pictographs, faces, symbols, extended-A
        or 0x1F000 <= cp <= 0x1F2FF   # tiles, enclosed characters
        or 0x2600 <= cp <= 0x27BF     # misc symbols and dingbats
        or 0x2190 <= cp <= 0x21FF     # arrows
        or 0x2B00 <= cp <= 0x2BFF     # extra arrows and stars
        or cp in (0x203C, 0x2049, 0x00A9, 0x00AE, 0x2122)
    )


@dataclass
class Caption:
    """One line (or wrapped block) of text, shown between two timestamps."""

    text: str
    start: float
    end: float
    position: str = "lower"
    scale: float = 1.0                 # multiplier on the base type size
    fade: float = 0.18                 # seconds of fade in and out
    align: str = "center"

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(
                f"caption {self.text!r}: end ({self.end}) must be after start ({self.start})"
            )
        if self.position not in CAPTION_POSITIONS:
            try:
                float(self.position)
            except (TypeError, ValueError):
                raise ValueError(
                    f"caption {self.text!r}: position must be one of "
                    f"{CAPTION_POSITIONS} or a 0-1 height fraction"
                ) from None

    @property
    def duration(self) -> float:
        return self.end - self.start

    def y_fraction(self) -> float:
        if self.position in _POSITION_Y:
            return _POSITION_Y[self.position]
        return float(self.position)


def parse_captions(data: Any) -> list[Caption]:
    """Build Caption objects from a list of dicts (config or JSON file)."""
    if not data:
        return []
    if isinstance(data, dict):
        data = data.get("captions", [])
    out: list[Caption] = []
    for i, raw in enumerate(data):
        if not isinstance(raw, dict):
            raise ValueError(f"caption #{i}: expected an object, got {type(raw).__name__}")
        known = {f.name for f in Caption.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        unknown = set(raw) - known - {"note"}
        if unknown:
            raise ValueError(f"caption #{i}: unknown key(s) {sorted(unknown)}")
        out.append(Caption(**{k: v for k, v in raw.items() if k in known}))
    out.sort(key=lambda c: c.start)
    return out


def validate_captions(caps: list[Caption], total_duration: float) -> list[str]:
    """Return human-readable warnings; overlapping or off-the-end captions."""
    notes: list[str] = []
    for i, c in enumerate(caps):
        if c.end > total_duration + 1e-3:
            notes.append(
                f"caption {i + 1} ({c.text[:28]!r}) ends at {c.end:.2f}s but the "
                f"cut is only {total_duration:.2f}s long"
            )
        if c.duration < 0.6:
            notes.append(
                f"caption {i + 1} ({c.text[:28]!r}) is on screen for only "
                f"{c.duration:.2f}s - too quick to read"
            )
        if i and c.start < caps[i - 1].end - 1e-3:
            notes.append(
                f"caption {i + 1} ({c.text[:28]!r}) starts before caption {i} ends; "
                "they will be stacked on top of each other"
            )
    return notes


# --- layout ---------------------------------------------------------------


@dataclass
class _Atom:
    kind: str          # "word" | "emoji"
    text: str
    width: float = 0.0
    image: Image.Image | None = None


def _emoji_image(ch: str, font: ImageFont.FreeTypeFont, target_h: int) -> Image.Image | None:
    """Rasterise one emoji at the font's native strike and scale it down."""
    canvas = Image.new("RGBA", (EMOJI_STRIKE * 2, EMOJI_STRIKE * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    try:
        draw.text((EMOJI_STRIKE // 4, EMOJI_STRIKE // 4), ch, font=font, embedded_color=True)
    except Exception as exc:  # pragma: no cover - font-specific
        log.debug("emoji %r failed to render: %s", ch, exc)
        return None
    bbox = canvas.getbbox()
    if not bbox:
        return None
    glyph = canvas.crop(bbox)
    ratio = target_h / glyph.height
    return glyph.resize(
        (max(1, round(glyph.width * ratio)), target_h), Image.LANCZOS
    )


def _tokenise(
    text: str,
    text_font: ImageFont.FreeTypeFont,
    emoji_font: ImageFont.FreeTypeFont | None,
    emoji_h: int,
) -> list[_Atom]:
    """Split a string into measurable atoms: words and individual emoji."""
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    atoms: list[_Atom] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        for word in re.split(r"(\s+)", buf):
            if not word.strip():
                continue
            atoms.append(_Atom("word", word, probe.textlength(word, font=text_font)))
        buf = ""

    for ch in text:
        if ch in _INVISIBLE:
            continue
        if is_emoji(ch):
            flush()
            if emoji_font is None:
                continue
            img = _emoji_image(ch, emoji_font, emoji_h)
            if img is not None:
                atoms.append(_Atom("emoji", ch, float(img.width), img))
        else:
            buf += ch
    flush()
    return atoms


def _wrap(atoms: list[_Atom], max_width: float, space: float) -> list[list[_Atom]]:
    lines: list[list[_Atom]] = []
    current: list[_Atom] = []
    width = 0.0
    for atom in atoms:
        add = atom.width + (space if current else 0.0)
        if current and width + add > max_width:
            lines.append(current)
            current, width = [atom], atom.width
        else:
            current.append(atom)
            width += add
    if current:
        lines.append(current)
    return lines


def render_caption(
    cfg: EditConfig,
    caption: Caption,
    path: str | Path,
) -> tuple[Path, int, int]:
    """Draw one caption to an RGBA PNG. Returns (path, width, height)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    base_px = max(18, round(cfg.height * cfg.caption_size * caption.scale))
    text_path = resolve_font(cfg.caption_font or cfg.watermark_font)
    text_font = (
        ImageFont.truetype(str(text_path), base_px)
        if text_path
        else ImageFont.load_default()
    )

    emoji_path = resolve_emoji_font(cfg.caption_emoji_font)
    emoji_font = None
    if emoji_path:
        try:
            emoji_font = ImageFont.truetype(str(emoji_path), EMOJI_STRIKE)
        except Exception as exc:  # pragma: no cover
            log.warning("colour-emoji font %s unusable (%s); emoji will be dropped",
                        emoji_path, exc)
    elif any(is_emoji(c) for c in caption.text):
        log.warning("no colour-emoji font found; emoji dropped from %r", caption.text[:40])

    ascent, descent = text_font.getmetrics()
    line_h = ascent + descent
    emoji_h = round(line_h * 0.98)
    space = ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(" ", font=text_font)

    atoms = _tokenise(caption.text, text_font, emoji_font, emoji_h)
    if not atoms:
        raise ValueError(f"caption {caption.text!r} rendered to nothing")

    max_width = cfg.width * cfg.caption_max_width
    lines = _wrap(atoms, max_width, space)

    stroke = max(2, round(base_px * cfg.caption_stroke))
    leading = round(line_h * cfg.caption_leading)
    pad = stroke * 3 + round(base_px * 0.18)

    widths = [
        sum(a.width for a in line) + space * max(0, len(line) - 1) for line in lines
    ]
    block_w = round(max(widths)) + pad * 2
    block_h = leading * len(lines) + pad * 2

    img = Image.new("RGBA", (block_w, block_h), (0, 0, 0, 0))

    # Soft drop shadow under everything, for separation from busy footage.
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)

    layers: list[tuple[Image.Image, ImageDraw.ImageDraw]] = [(shadow, sdraw)]
    main_draw = ImageDraw.Draw(img)
    layers.append((img, main_draw))

    for target, draw in layers:
        is_shadow = target is shadow
        y = pad
        for line, line_w in zip(lines, widths, strict=True):
            x = pad + (max(widths) - line_w) / 2 if caption.align == "center" else pad
            for atom in line:
                if atom.kind == "word":
                    if is_shadow:
                        draw.text(
                            (x, y), atom.text, font=text_font,
                            fill=(0, 0, 0, 220), stroke_width=stroke,
                            stroke_fill=(0, 0, 0, 220),
                        )
                    else:
                        draw.text(
                            (x, y), atom.text, font=text_font,
                            fill=cfg.caption_colour, stroke_width=stroke,
                            stroke_fill=cfg.caption_stroke_colour,
                        )
                elif atom.image is not None:
                    pos = (round(x), round(y + (line_h - atom.image.height) / 2))
                    if is_shadow:
                        # Drop the glyph's silhouette into the shadow pass so
                        # emoji get the same soft dark halo the text does;
                        # without it a pale emoji vanishes on pale footage.
                        silhouette = Image.new("RGBA", atom.image.size, (0, 0, 0, 255))
                        silhouette.putalpha(atom.image.getchannel("A"))
                        target.alpha_composite(silhouette, pos)
                    else:
                        target.alpha_composite(atom.image, pos)
                x += atom.width + space
            y += leading

    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1.0, base_px * 0.05)))
    out = Image.alpha_composite(shadow, img)

    if cfg.caption_opacity < 1.0:
        alpha = out.getchannel("A").point(
            lambda v: round(v * max(0.0, min(1.0, cfg.caption_opacity)))
        )
        out.putalpha(alpha)

    out.save(path)
    log.info(
        "caption %.2f-%.2fs: %r (%dx%d%s)",
        caption.start, caption.end,
        unicodedata.normalize("NFC", caption.text)[:42],
        out.width, out.height,
        "" if emoji_font else ", no emoji font",
    )
    return path, out.width, out.height


def caption_overlay_xy(cfg: EditConfig, caption: Caption, w: int, h: int) -> tuple[int, int]:
    """Top-left corner for the overlay, from the caption's anchor."""
    x = round((cfg.width - w) / 2)
    y = round(cfg.height * caption.y_fraction() - h / 2)
    margin = round(cfg.height * 0.02)
    y = max(margin, min(y, cfg.height - h - margin))
    return x, y
