"""Aspect-ratio conversion — the "CapCut ratio" behaviour, done properly.

Four strategies, all of which produce a pixel-perfect ``work_w x work_h``
canvas no matter what the source looks like:

``crop``   full-bleed fill, centre (or focus-point) crop. Zero empty space.
``blur``   source fitted whole, gaps filled with a blurred, dimmed copy of
           itself — what CapCut calls "blur background".
``fit``    source fitted whole, gaps filled with a flat colour.
``smart``  pre-crops an ultra-wide source toward 4:3-ish, then blur-fills, so
           the subject is noticeably larger than a plain letterbox.
``auto``   picks ``crop`` for portrait/square sources (nothing meaningful is
           lost) and ``smart`` for landscape sources (nothing is cut off).
"""

from __future__ import annotations

from .config import EditConfig
from .probe import MediaInfo

# A full-bleed crop that throws away more than this fraction of the source is
# too destructive to apply blindly — subjects start walking out of frame.
MAX_AUTO_CROP_LOSS = 0.32


def crop_loss(source_aspect: float, canvas_aspect: float) -> float:
    """Fraction of the source image a full-bleed crop would discard (0..1)."""
    if source_aspect <= 0 or canvas_aspect <= 0:
        return 0.0
    if source_aspect > canvas_aspect:          # source wider -> sides are cut
        return 1.0 - canvas_aspect / source_aspect
    return 1.0 - source_aspect / canvas_aspect  # source taller -> top/bottom cut


def resolve_fill(info: MediaInfo, cfg: EditConfig, canvas_aspect: float) -> str:
    """Resolve ``auto`` into a concrete strategy.

    Cheap crop (little is lost) -> full-bleed, because edge-to-edge image is
    what makes a vertical video feel native. Expensive crop -> keep the whole
    frame and fill the gaps instead, because cropping half the picture away
    costs far more views than a pair of soft bars ever will.
    """
    if cfg.fill != "auto":
        return cfg.fill
    src = info.aspect or canvas_aspect
    if crop_loss(src, canvas_aspect) <= MAX_AUTO_CROP_LOSS:
        return "crop"
    return "smart" if canvas_aspect <= 1.0 else "blur"


def _even(value: float) -> int:
    return max(2, int(round(value / 2) * 2))


def build_framing(
    info: MediaInfo,
    cfg: EditConfig,
    work_w: int,
    work_h: int,
    in_label: str,
    out_label: str,
) -> tuple[list[str], str]:
    """Return ``(graph_segments, resolved_mode)``."""
    mode = resolve_fill(info, cfg, work_w / work_h)
    fx = min(max(cfg.focus_x, 0.0), 1.0)
    fy = min(max(cfg.focus_y, 0.0), 1.0)
    segments: list[str] = []

    if mode == "crop":
        segments.append(
            f"[{in_label}]scale={work_w}:{work_h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={work_w}:{work_h}:(iw-ow)*{fx:.4f}:(ih-oh)*{fy:.4f},setsar=1[{out_label}]"
        )
        return segments, mode

    if mode == "fit":
        segments.append(
            f"[{in_label}]scale={work_w}:{work_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={work_w}:{work_h}:(ow-iw)/2:(oh-ih)/2:color={cfg.pad_color},setsar=1[{out_label}]"
        )
        return segments, mode

    # --- blur / smart -------------------------------------------------------
    src = f"{in_label}"
    if mode == "smart" and info.aspect > cfg.smart_max_aspect:
        # Gently crop the sides of an ultra-wide source first so the subject
        # fills more of the vertical frame, then blur-fill the remainder.
        target_ar = cfg.smart_max_aspect
        segments.append(
            f"[{src}]crop=ih*{target_ar:.4f}:ih:(iw-ow)*{fx:.4f}:0,setsar=1[pre]"
        )
        src = "pre"

    # Background: downscale -> blur -> upscale (identical look, ~8x faster).
    small_w, small_h = _even(work_w / 4), _even(work_h / 4)
    sigma = max(2.0, 9.0 * cfg.blur_strength)
    dim = max(0.0, min(0.5, cfg.bg_dim))
    segments.append(f"[{src}]split=2[bgsrc][fgsrc]")
    segments.append(
        f"[bgsrc]scale={small_w}:{small_h}:force_original_aspect_ratio=increase:flags=bilinear,"
        f"crop={small_w}:{small_h},gblur=sigma={sigma:.2f}:steps=3,"
        f"scale={work_w}:{work_h}:flags=bicubic,"
        f"eq=brightness=-{dim:.3f}:saturation=1.06:contrast=1.02,setsar=1[bg]"
    )
    segments.append(
        f"[fgsrc]scale={work_w}:{work_h}:force_original_aspect_ratio=decrease:flags=lanczos,setsar=1[fg]"
    )
    segments.append(
        f"[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2:eval=init:format=auto,setsar=1[{out_label}]"
    )
    return segments, mode


def framing_report(info: MediaInfo, cfg: EditConfig, mode: str) -> str:
    """One-line human explanation of what the framing step decided to do."""
    target = f"{cfg.width}x{cfg.height}"
    if mode == "crop":
        return f"{info.width}x{info.height} -> {target} · full-bleed crop (no bars)"
    if mode == "fit":
        return f"{info.width}x{info.height} -> {target} · fit inside {cfg.pad_color} bars"
    if mode == "smart":
        return (
            f"{info.width}x{info.height} -> {target} · smart fill "
            f"(sides trimmed to {cfg.smart_max_aspect:g}:1, blurred background)"
        )
    return f"{info.width}x{info.height} -> {target} · blurred background fill"
