"""Colour grading and detail presets.

Every preset is deliberately conservative. Social platforms re-encode hard;
a little extra contrast and micro-contrast survives that process, heavy
grading turns into banding and mush.
"""

from __future__ import annotations

from .config import EditConfig

_GRADES: dict[str, list[str]] = {
    "none": [],
    "clean": [
        "eq=contrast=1.05:saturation=1.08:gamma=1.00",
    ],
    "vivid": [
        "eq=contrast=1.11:saturation=1.22:gamma=0.985",
        "colorlevels=rimin=0.012:gimin=0.012:bimin=0.012",
    ],
    "cinematic": [
        "curves=preset=medium_contrast",
        "eq=saturation=0.98",
        "colorbalance=rs=-0.015:gs=-0.004:bs=0.030:rm=0.012:bm=-0.012",
    ],
    "warm": [
        "eq=contrast=1.06:saturation=1.14",
        "colorbalance=rm=0.035:gm=0.008:bm=-0.030",
    ],
}

# unsharp amount per preset, scaled by cfg.sharpen
_SHARPEN_BASE: dict[str, float] = {
    "none": 0.0,
    "clean": 0.32,
    "vivid": 0.48,
    "cinematic": 0.30,
    "warm": 0.35,
}


def build_grade(cfg: EditConfig) -> list[str]:
    """Return a list of filter strings (may be empty) for the look stage."""
    chain: list[str] = []
    if cfg.denoise:
        # Light temporal+spatial clean-up; helps compressed sources a lot.
        chain.append("hqdn3d=1.5:1.5:6:6")
    chain.extend(_GRADES.get(cfg.grade, []))
    amount = _SHARPEN_BASE.get(cfg.grade, 0.3) * max(0.0, cfg.sharpen)
    if amount > 0.01:
        chain.append(f"unsharp=5:5:{amount:.3f}:5:5:0.0")
    return chain
