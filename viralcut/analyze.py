"""Source analysis used to pick hooks and trim points.

Two cheap passes over the source produce everything needed to answer
"where does this clip actually get interesting?":

* scene-change detection (FFmpeg's ``scene`` score)
* momentary loudness over time (EBU R128)

The combination is scored over a sliding window so the editor can start on
the strongest moment instead of a slow intro — the single biggest retention
lever on short-form platforms.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .ffmpeg_tool import find_ffmpeg, run
from .probe import MediaInfo, probe

log = logging.getLogger("viralcut.analyze")

_SCENE_TIME = re.compile(r"pts_time:(\d+(?:\.\d+)?)")
_R128_M = re.compile(r"pts_time:(\d+(?:\.\d+)?)[^\n]*\n[^\n]*lavfi\.r128\.M=(-?\d+(?:\.\d+)?)")


@dataclass
class Analysis:
    info: MediaInfo
    scene_cuts: list[float] = field(default_factory=list)
    loudness: list[tuple[float, float]] = field(default_factory=list)
    best_window: tuple[float, float] | None = None
    window_scores: list[tuple[float, float]] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"source      : {self.info.summary()}",
            f"scene cuts  : {len(self.scene_cuts)}"
            + (f" (every {self.info.duration / len(self.scene_cuts):.1f}s avg)"
               if self.scene_cuts and self.info.duration else ""),
        ]
        if self.loudness:
            peak = max(self.loudness, key=lambda x: x[1])
            lines.append(f"loudest at  : {peak[0]:.1f}s ({peak[1]:.1f} LUFS momentary)")
        if self.best_window:
            s, e = self.best_window
            lines.append(f"best window : {s:.1f}s -> {e:.1f}s  (use --start {s:.1f} --end {e:.1f})")
        if self.scene_cuts:
            preview = ", ".join(f"{t:.1f}s" for t in self.scene_cuts[:12])
            lines.append(f"first cuts  : {preview}{' ...' if len(self.scene_cuts) > 12 else ''}")
        return "\n".join(lines)


def detect_scenes(source: str | Path, threshold: float = 0.28) -> list[float]:
    args = [
        find_ffmpeg(), "-hide_banner", "-nostdin", "-i", str(source),
        "-filter_complex", f"[0:v]select='gt(scene,{threshold})',metadata=print:file=-",
        "-an", "-f", "null", "-",
    ]
    res = run(args, check=False, quiet=True)
    times = [float(t) for t in _SCENE_TIME.findall(res.stdout + res.stderr)]
    return sorted({round(t, 3) for t in times})


def measure_loudness_curve(source: str | Path) -> list[tuple[float, float]]:
    """Momentary loudness (400 ms window) over time, as ``(seconds, LUFS)``."""
    args = [
        find_ffmpeg(), "-hide_banner", "-nostdin", "-i", str(source),
        "-filter_complex",
        "[0:a]ebur128=metadata=1,ametadata=print:key=lavfi.r128.M:file=-",
        "-f", "null", "-",
    ]
    res = run(args, check=False, quiet=True)
    out: list[tuple[float, float]] = []
    for t, m in _R128_M.findall(res.stdout + "\n" + res.stderr):
        try:
            out.append((float(t), float(m)))
        except ValueError:
            continue
    return out


def score_windows(
    analysis: Analysis, window: float, step: float = 0.5
) -> list[tuple[float, float]]:
    """Score every candidate start time. Higher = more going on."""
    duration = analysis.info.duration
    if duration <= window:
        return [(0.0, 1.0)]
    scores: list[tuple[float, float]] = []
    loud = analysis.loudness
    t = 0.0
    while t + window <= duration:
        cuts = sum(1 for c in analysis.scene_cuts if t <= c < t + window)
        in_window = [m for ts, m in loud if t <= ts < t + window and m > -70]
        avg_loud = sum(in_window) / len(in_window) if in_window else -40.0
        # Normalise: loudness from -40..-5 LUFS -> 0..1; cuts saturate at ~8.
        loud_score = max(0.0, min(1.0, (avg_loud + 40.0) / 35.0))
        cut_score = min(1.0, cuts / 8.0)
        # Earlier is better, all else equal (audiences keep scrolling).
        position_bonus = max(0.0, 0.12 * (1 - t / duration))
        scores.append((round(t, 2), round(0.58 * cut_score + 0.42 * loud_score + position_bonus, 4)))
        t += step
    return scores


def analyze(source: str | Path, target_window: float | None = None) -> Analysis:
    info = probe(source)
    log.info("analysing %s", Path(source).name)
    result = Analysis(info=info)
    result.scene_cuts = detect_scenes(source)
    if info.has_audio:
        result.loudness = measure_loudness_curve(source)
    window = target_window or min(max(15.0, info.duration * 0.35), 45.0)
    if info.duration > window + 1:
        result.window_scores = score_windows(result, window)
        if result.window_scores:
            best_start = max(result.window_scores, key=lambda x: x[1])[0]
            # Snap to the nearest scene cut within 1.5 s — cleaner entry point.
            near = [c for c in result.scene_cuts if abs(c - best_start) <= 1.5]
            if near:
                best_start = min(near, key=lambda c: abs(c - best_start))
            result.best_window = (round(best_start, 2), round(min(info.duration, best_start + window), 2))
    return result
