"""Edit configuration: canvas, framing, look, timing, branding, encoding."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

# Aspect-ratio shortcuts -> (width, height) at 1080p-class resolution.
RATIOS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),   # TikTok / Shorts / Reels (default)
    "4:5": (1080, 1350),    # Instagram feed
    "1:1": (1080, 1080),    # square feed
    "16:9": (1920, 1080),   # YouTube landscape
    "2:3": (1080, 1620),    # Pinterest
}

FILL_MODES = ("auto", "crop", "blur", "fit", "smart")
ZOOM_MODES = ("off", "push", "hook")
GRADE_PRESETS = ("none", "clean", "vivid", "cinematic", "warm")
INTRO_STYLES = ("none", "blurzoom", "flash", "fade", "whip")
OUTRO_STYLES = ("none", "blurout", "fade", "zoomout")
WATERMARK_STYLES = ("shadow", "pill", "outline", "plain")
WATERMARK_POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right")


@dataclass
class EditConfig:
    """Every knob of the finishing pipeline, in one serialisable object."""

    # --- canvas -------------------------------------------------------------
    ratio: str = "9:16"
    width: int = 1080
    height: int = 1920
    fps: int = 60
    interpolate: bool = False          # true motion interpolation to reach fps

    # --- framing (the "CapCut aspect ratio" behaviour) ----------------------
    fill: str = "auto"
    focus_x: float = 0.5               # 0 = left edge, 1 = right edge
    focus_y: float = 0.5               # 0 = top edge, 1 = bottom edge
    blur_strength: float = 1.0         # background blur multiplier
    bg_dim: float = 0.06               # darken the blurred background
    pad_color: str = "black"
    smart_max_aspect: float = 1.30     # 'smart' pre-crops wider sources to this AR

    # --- motion -------------------------------------------------------------
    zoom: str = "push"
    zoom_amount: float = 0.06          # 6 % travel
    hook_seconds: float = 1.2          # length of the 'hook' punch

    # --- look ---------------------------------------------------------------
    grade: str = "clean"
    sharpen: float = 1.0               # multiplier on the unsharp amount
    denoise: bool = False
    stabilize: bool = False

    # --- timing -------------------------------------------------------------
    start: float | None = None
    end: float | None = None
    max_duration: float | None = None
    speed: float = 1.0

    # --- intro / outro ------------------------------------------------------
    intro: str = "blurzoom"
    intro_duration: float = 0.45
    outro: str = "blurout"
    outro_duration: float = 0.70

    # --- branding -----------------------------------------------------------
    watermark_text: str = "@Lowk67Tuff"
    watermark_image: str | None = None
    watermark_position: str = "top-left"
    watermark_style: str = "shadow"
    watermark_opacity: float = 0.88
    watermark_scale: float = 1.0
    watermark_margin_x: float = 0.050  # fraction of canvas width
    watermark_margin_y: float = 0.045  # fraction of canvas height
    watermark_font: str | None = None

    # --- captions -----------------------------------------------------------
    # Off unless a cut explicitly asks for them. Each entry is
    # {"text", "start", "end", "position", "scale", "fade", "align"}.
    captions: list[dict[str, Any]] = field(default_factory=list)
    caption_size: float = 0.0345      # type height as a fraction of canvas height
    caption_max_width: float = 0.86    # wrap before the block gets this wide
    caption_leading: float = 1.12      # line spacing, times the line height
    caption_stroke: float = 0.085      # outline weight, times the type size
    caption_colour: str = "#FFFFFF"
    caption_stroke_colour: str = "#000000"
    caption_opacity: float = 1.0
    caption_font: str | None = None
    caption_emoji_font: str | None = None

    # --- audio --------------------------------------------------------------
    keep_audio: bool = True
    loudness_target: float = -14.0     # LUFS, the TikTok/YouTube/IG norm
    true_peak: float = -1.0            # dBTP
    loudnorm_passes: int = 2
    audio_fade: float = 0.25           # seconds, in and out
    silent_track_if_missing: bool = True

    # --- encode -------------------------------------------------------------
    crf: int = 18
    x264_preset: str = "slow"
    max_bitrate: str = "24M"
    bufsize: str = "48M"
    audio_bitrate: str = "320k"
    faststart: bool = True

    # --- misc ---------------------------------------------------------------
    notes: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ utils
    def __post_init__(self) -> None:
        self.apply_ratio(self.ratio)
        self.validate()

    def apply_ratio(self, ratio: str) -> None:
        if ratio in RATIOS:
            self.ratio = ratio
            self.width, self.height = RATIOS[ratio]
        elif ratio and ":" in ratio:
            a, _, b = ratio.partition(":")
            try:
                num, den = float(a), float(b)
            except ValueError as exc:
                raise ValueError(f"Invalid ratio: {ratio!r}") from exc
            if num <= 0 or den <= 0:
                raise ValueError(f"Invalid ratio: {ratio!r}")
            if num < den:   # portrait -> lock the long edge to 1920
                h = 1920
                w = int(round(h * num / den / 2) * 2)
            else:           # landscape/square -> lock the long edge to 1920
                w = 1920 if num > den else 1080
                h = int(round(w * den / num / 2) * 2)
            self.ratio, self.width, self.height = ratio, w, h

    def validate(self) -> None:
        if self.fill not in FILL_MODES:
            raise ValueError(f"fill must be one of {FILL_MODES}")
        if self.zoom not in ZOOM_MODES:
            raise ValueError(f"zoom must be one of {ZOOM_MODES}")
        if self.grade not in GRADE_PRESETS:
            raise ValueError(f"grade must be one of {GRADE_PRESETS}")
        if self.intro not in INTRO_STYLES:
            raise ValueError(f"intro must be one of {INTRO_STYLES}")
        if self.outro not in OUTRO_STYLES:
            raise ValueError(f"outro must be one of {OUTRO_STYLES}")
        if self.watermark_style not in WATERMARK_STYLES:
            raise ValueError(f"watermark_style must be one of {WATERMARK_STYLES}")
        if self.watermark_position not in WATERMARK_POSITIONS:
            raise ValueError(f"watermark_position must be one of {WATERMARK_POSITIONS}")
        if not 0.1 <= self.speed <= 4.0:
            raise ValueError("speed must be between 0.1 and 4.0")
        if not 0.0 <= self.watermark_opacity <= 1.0:
            raise ValueError("watermark_opacity must be between 0 and 1")
        if self.width % 2 or self.height % 2:
            raise ValueError("canvas dimensions must be even")

    # --------------------------------------------------------------- (de)ser
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EditConfig:
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown config keys: {', '.join(sorted(unknown))}")
        return cls(**data)

    @classmethod
    def load(cls, path: str | Path) -> EditConfig:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Platform presets. All of them render a 1080x1920 / 60 fps master; they only
# differ in the finishing touches that each algorithm rewards.
# --------------------------------------------------------------------------
PRESETS: dict[str, dict[str, Any]] = {
    "tiktok": {
        "ratio": "9:16", "fps": 60, "grade": "vivid", "sharpen": 1.1,
        "zoom": "push", "zoom_amount": 0.06,
        "intro": "blurzoom", "intro_duration": 0.40,
        "outro": "blurout", "outro_duration": 0.65,
        "loudness_target": -14.0, "crf": 18,
    },
    "shorts": {
        "ratio": "9:16", "fps": 60, "grade": "clean", "sharpen": 1.0,
        "zoom": "push", "zoom_amount": 0.05,
        "intro": "blurzoom", "intro_duration": 0.45,
        "outro": "blurout", "outro_duration": 0.70,
        "loudness_target": -14.0, "crf": 17,
    },
    "reels": {
        "ratio": "9:16", "fps": 60, "grade": "vivid", "sharpen": 1.15,
        "zoom": "push", "zoom_amount": 0.06,
        "intro": "flash", "intro_duration": 0.35,
        "outro": "fade", "outro_duration": 0.60,
        "loudness_target": -14.0, "crf": 18,
    },
    "master": {  # highest quality archival master, neutral look
        "ratio": "9:16", "fps": 60, "grade": "clean", "sharpen": 0.8,
        "zoom": "off", "intro": "fade", "outro": "fade",
        "crf": 15, "x264_preset": "slow", "max_bitrate": "40M", "bufsize": "80M",
    },
}


def build_config(preset: str = "shorts", **overrides: Any) -> EditConfig:
    """Create an :class:`EditConfig` from a preset plus explicit overrides."""
    if preset not in PRESETS:
        raise ValueError(f"Unknown preset {preset!r}. Available: {', '.join(PRESETS)}")
    data: dict[str, Any] = dict(PRESETS[preset])
    data.update({k: v for k, v in overrides.items() if v is not None})
    cfg = EditConfig(**data)
    cfg.notes["preset"] = preset
    return cfg
