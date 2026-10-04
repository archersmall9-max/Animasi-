"""Intro / outro plates.

A "plate" is a very short clip generated from the first (or last) frame of the
*already framed and graded* video. Because the plate resolves to exactly the
frame the body starts on, the join is invisible: the result reads as a single
animated move — a blur-zoom reveal on the way in, a blur-out on the way out —
with no third-party templates, stingers or music involved.

Frames are streamed straight into FFmpeg as raw RGB, so no giant PNG sequence
is ever written to disk.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

from .config import EditConfig
from .ffmpeg_tool import find_ffmpeg

log = logging.getLogger("viralcut.plates")


# ----------------------------------------------------------------- easings --
def ease_out_cubic(p: float) -> float:
    return 1.0 - (1.0 - p) ** 3


def ease_in_cubic(p: float) -> float:
    return p ** 3


def ease_in_out(p: float) -> float:
    return 4 * p ** 3 if p < 0.5 else 1 - ((-2 * p + 2) ** 3) / 2


# ------------------------------------------------------------ image helpers --
def zoom_image(img: Image.Image, factor: float) -> Image.Image:
    """Centre zoom by ``factor`` (1.0 = untouched), keeping the frame size."""
    if abs(factor - 1.0) < 1e-4:
        return img
    w, h = img.size
    if factor > 1.0:
        cw, ch = max(2, int(w / factor)), max(2, int(h / factor))
        left, top = (w - cw) // 2, (h - ch) // 2
        return img.crop((left, top, left + cw, top + ch)).resize((w, h), Image.LANCZOS)
    # factor < 1 -> shrink on a black canvas
    nw, nh = max(2, int(w * factor)), max(2, int(h * factor))
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    canvas.paste(img.resize((nw, nh), Image.LANCZOS), ((w - nw) // 2, (h - nh) // 2))
    return canvas


def blur_image(img: Image.Image, radius: float) -> Image.Image:
    """Gaussian blur; heavy radii are computed at half resolution for speed."""
    if radius < 0.4:
        return img
    if radius > 3:
        w, h = img.size
        small = img.resize((max(2, w // 2), max(2, h // 2)), Image.BILINEAR)
        small = small.filter(ImageFilter.GaussianBlur(radius / 2))
        return small.resize((w, h), Image.BICUBIC)
    return img.filter(ImageFilter.GaussianBlur(radius))


def brightness(img: Image.Image, factor: float) -> Image.Image:
    if abs(factor - 1.0) < 1e-3:
        return img
    return ImageEnhance.Brightness(img).enhance(max(0.0, factor))


def mix_white(img: Image.Image, amount: float) -> Image.Image:
    if amount <= 0.001:
        return img
    white = Image.new("RGB", img.size, (255, 255, 255))
    return Image.blend(img, white, min(1.0, amount))


def horizontal_smear(img: Image.Image, strength: float) -> Image.Image:
    """Cheap directional (whip-pan) blur."""
    if strength <= 0.01:
        return img
    w, h = img.size
    span = max(1, int(w * 0.10 * strength))
    acc = img.convert("RGB")
    for i in range(1, 5):
        shifted = img.transform(
            (w, h), Image.AFFINE, (1, 0, -(span * i / 4), 0, 1, 0), resample=Image.BILINEAR
        )
        acc = Image.blend(acc, shifted, 1.0 / (i + 1))
    return acc


# --------------------------------------------------------------- generators --
def intro_frames(
    base: Image.Image, cfg: EditConfig, count: int, base_zoom: float
) -> Iterator[Image.Image]:
    """Frames that resolve *into* ``base`` (the body's first frame)."""
    style = cfg.intro
    for i in range(count):
        # Spans (almost) the full 0..1 range: the first frame carries the
        # effect at full strength, the last lands on the body's own frame.
        p = (i + 0.5) / count
        e = ease_out_cubic(p)
        frame = base
        if style == "blurzoom":
            frame = zoom_image(frame, base_zoom * (1.0 + 0.13 * (1 - e)))
            frame = blur_image(frame, 24.0 * (1 - e) ** 1.2)
            frame = brightness(frame, 0.80 + 0.20 * e)
        elif style == "flash":
            frame = zoom_image(frame, base_zoom * (1.0 + 0.05 * (1 - e)))
            frame = mix_white(frame, 0.95 * (1 - e) ** 1.4)
        elif style == "fade":
            frame = zoom_image(frame, base_zoom * (1.0 + 0.035 * (1 - e)))
            frame = brightness(frame, e)
        elif style == "whip":
            frame = zoom_image(frame, base_zoom * (1.0 + 0.07 * (1 - e)))
            frame = horizontal_smear(frame, (1 - e) * 1.6)
            frame = brightness(frame, 0.85 + 0.15 * e)
        else:
            frame = zoom_image(frame, base_zoom)
        yield frame.convert("RGB")


def outro_frames(
    base: Image.Image, cfg: EditConfig, count: int, base_zoom: float
) -> Iterator[Image.Image]:
    """Frames that continue *out of* ``base`` (the body's last frame)."""
    style = cfg.outro
    for i in range(count):
        p = (i + 0.5) / count
        e = ease_in_out(p)
        frame = base
        if style == "blurout":
            frame = zoom_image(frame, base_zoom * (1.0 + 0.10 * e))
            frame = blur_image(frame, 26.0 * ease_in_cubic(p))
            frame = brightness(frame, max(0.0, 1.0 - 1.05 * e ** 1.15))
        elif style == "fade":
            frame = zoom_image(frame, base_zoom * (1.0 + 0.03 * e))
            frame = brightness(frame, max(0.0, 1.0 - e ** 1.05))
        elif style == "zoomout":
            frame = zoom_image(frame, base_zoom * max(0.55, 1.0 - 0.22 * e))
            frame = brightness(frame, max(0.0, 1.0 - 0.95 * e ** 1.3))
        else:
            frame = zoom_image(frame, base_zoom)
        yield frame.convert("RGB")


# ------------------------------------------------------------------ encoding --
def encode_plate(
    frames: Iterator[Image.Image],
    size: tuple[int, int],
    fps: int,
    out_path: str | Path,
) -> Path:
    """Stream RGB frames into a near-lossless intermediate clip."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    cmd = [
        find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
        "-framerate", str(fps), "-i", "pipe:0",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
        "-pix_fmt", "yuv420p", "-fps_mode", "cfr", "-r", str(fps),
        str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE)
    assert proc.stdin is not None
    written = 0
    try:
        for frame in frames:
            if frame.size != (width, height):
                frame = frame.resize((width, height), Image.LANCZOS)
            proc.stdin.write(frame.tobytes())
            written += 1
    finally:
        proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        code = proc.wait()
    if code != 0:
        raise RuntimeError(f"Plate encode failed ({code}): {stderr[-800:]}")
    log.info("plate: %s (%d frames)", out.name, written)
    return out


def build_plate(
    base: Image.Image,
    cfg: EditConfig,
    kind: str,
    duration: float,
    base_zoom: float,
    out_path: str | Path,
) -> tuple[Path, float] | None:
    """Build an intro or outro plate. Returns ``(path, duration)`` or ``None``."""
    style = cfg.intro if kind == "intro" else cfg.outro
    if style == "none" or duration <= 0:
        return None
    count = max(2, int(round(duration * cfg.fps)))
    gen: Callable[..., Iterator[Image.Image]] = intro_frames if kind == "intro" else outro_frames
    path = encode_plate(
        gen(base, cfg, count, base_zoom), (cfg.width, cfg.height), cfg.fps, out_path
    )
    return path, count / cfg.fps
