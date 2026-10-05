"""Assemble several shots into one body, with the cuts on the beat.

This is the part that makes an edit read as an edit rather than a slideshow.
A montage needs three things to be right at once:

* every cut lands on a beat (:mod:`viralcut.beats` finds them)
* each shot is long enough to register and short enough not to drag
* the transitions are the same length everywhere, so the rhythm is even

The output is a single intermediate video that the normal pipeline then
treats as its source, which keeps framing, grading, captions, watermark and
the intro/outro in one place instead of reimplementing them here. That costs
one extra encode, so the intermediate is written at CRF 10 - far above the
delivery bitrate, where the loss is not measurable in the final file.

Hard cuts and cross-fades are built differently on purpose. ``xfade``
cannot do a zero-length transition, and a montage of hard cuts is the more
common shape, so that path uses ``concat`` and avoids the overlap
arithmetic entirely.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path

from .beats import BeatGrid
from .config import EditConfig
from .ffmpeg_tool import run_ffmpeg
from .probe import probe

log = logging.getLogger(__name__)

# xfade transitions worth having. The full set has 58 entries, most of
# which look like a 2003 PowerPoint.
TRANSITIONS = (
    "cut",          # not an xfade - handled by concat
    "fade",
    "fadeblack",
    "fadewhite",
    "wipeleft",
    "wiperight",
    "wipeup",
    "wipedown",
    "slideleft",
    "slideright",
    "circleopen",
    "circleclose",
    "radial",
    "dissolve",
    "pixelize",
    "hblur",
    "zoomin",
)


@dataclass
class Shot:
    """One piece of footage in the montage."""

    source: str | Path
    start: float = 0.0              # in-point within the source
    duration: float | None = None   # filled in by :func:`plan_shots`
    label: str = ""
    # Framing. A montage cut from one film runs out of camera angles fast:
    # three consecutive shots of the same wide master do not read as cuts,
    # they read as a glitch. ``zoom`` punches in and ``focus_x``/``focus_y``
    # slide the window, so one master yields wide / medium / close framings.
    zoom: float = 1.0               # 1.0 = full frame, 1.4 = 40 % punch-in
    focus_x: float = 0.5            # 0 = hard left, 1 = hard right
    focus_y: float = 0.5            # 0 = top, 1 = bottom

    def __post_init__(self) -> None:
        self.source = Path(self.source).expanduser()
        if self.start < 0:
            raise ValueError(f"shot start must not be negative: {self.start}")
        if self.duration is not None and self.duration <= 0:
            raise ValueError(f"shot duration must be positive: {self.duration}")
        if self.zoom < 1.0:
            raise ValueError(f"shot zoom must be >= 1.0: {self.zoom}")
        if not 0.0 <= self.focus_x <= 1.0:
            raise ValueError(f"focus_x must be within 0..1: {self.focus_x}")
        if not 0.0 <= self.focus_y <= 1.0:
            raise ValueError(f"focus_y must be within 0..1: {self.focus_y}")


@dataclass
class MontagePlan:
    """The resolved cut list."""

    shots: list[Shot]
    transition: str = "cut"
    transition_duration: float = 0.0
    cut_times: list[float] = field(default_factory=list)   # output clock
    grid_confidence: float = 0.0
    tempo: float = 0.0

    @property
    def duration(self) -> float:
        """Length of the assembled body, overlaps accounted for."""
        total = sum(s.duration or 0.0 for s in self.shots)
        if self.transition == "cut":
            return total
        # Every join overlaps its two neighbours by one transition.
        return total - self.transition_duration * max(len(self.shots) - 1, 0)


def plan_shots(shots: list[Shot], grid: BeatGrid, *,
               beats_per_shot: int = 4,
               start_beat: int = 0,
               transition_duration: float = 0.0,
               max_duration: float | None = None,
               min_shot: float = 0.35,
               fps: int | None = None) -> MontagePlan:
    """Give every shot a duration that ends on a beat.

    ``beats_per_shot`` is the cut density: 4 is one bar per shot, 2 is
    twice as fast, 8 lets a moment breathe. Shots with an explicit duration
    already set are left alone, so a single held shot can sit inside an
    otherwise rhythmic sequence.

    A cross-fade eats into both neighbours, so each shot is lengthened by
    the transition duration. Without that the *visible* part of each shot
    would be short by one transition and the cuts would creep early.

    Pass ``fps`` and the cut points are quantised to whole frames on the
    output clock. This is not a detail: ffmpeg rounds each shot's length up
    to a whole frame independently, so without it the rounding *accumulates*
    and the montage slides off the beat. Measured on four shots at 30 fps
    the drift was already 82 ms by the end. Quantising the cut times and
    deriving each duration as the gap between them holds the error to half
    a frame, and stops it compounding.
    """
    if not shots:
        raise ValueError("a montage needs at least one shot")
    if beats_per_shot < 1:
        raise ValueError("beats_per_shot must be at least 1")

    beats = list(grid.beats)
    raw: list[float] = []

    for i, shot in enumerate(shots):
        if shot.duration is not None:
            dur = shot.duration
        else:
            first = start_beat + i * beats_per_shot
            last = first + beats_per_shot
            if last < len(beats):
                dur = beats[last] - beats[first]
            elif grid.period > 0:
                # Ran off the end of the analysed track: keep the rhythm
                # going at the nominal tempo rather than stopping dead.
                dur = grid.period * beats_per_shot
            else:
                dur = 1.0
        raw.append(max(dur, min_shot))

    # Cut points on the output clock, before any transition overlap.
    edges = [0.0]
    for dur in raw:
        edges.append(edges[-1] + dur)

    if fps:
        edges = [round(e * fps) / fps for e in edges]

    planned: list[Shot] = []
    cut_times: list[float] = []
    for i, shot in enumerate(shots):
        visible = edges[i + 1] - edges[i]
        if visible < min_shot / 2:
            continue
        if max_duration is not None and edges[i] >= max_duration:
            log.info("montage truncated to %d shots by max_duration", len(planned))
            break
        if max_duration is not None and edges[i + 1] > max_duration:
            visible = max_duration - edges[i]
            if visible < min_shot:
                log.info("montage truncated to %d shots by max_duration", len(planned))
                break
        # A cross-fade consumes one transition's worth of footage from the
        # shot it fades *into*, so every shot but the last has to supply
        # that much extra. Padding the last one too would leave a tail with
        # nothing to blend against and run the montage one transition long.
        pad = transition_duration if i < len(shots) - 1 else 0.0
        planned.append(replace(shot, duration=visible + pad))
        cut_times.append(edges[i] + visible)

    return MontagePlan(
        shots=planned,
        transition_duration=transition_duration,
        cut_times=cut_times,
        grid_confidence=grid.confidence,
        tempo=grid.tempo,
    )


def _shot_chain(index: int, shot: Shot, cfg: EditConfig, fps: int) -> str:
    """Scale one shot to the canvas and trim it to an exact frame count.

    Every shot has to arrive at the same size, pixel format and frame rate
    before it can be concatenated or cross-faded - ffmpeg refuses otherwise,
    and the error is not a helpful one. Cover-scaling keeps the frame full
    rather than letterboxing a source of the wrong shape.

    Two details here were each a bug first.

    The trim is by *frame count*, inside the graph, rather than ``-t`` on
    the input. Input trimming cuts at the first frame whose timestamp
    reaches the limit, which rounds up: four shots of 1.867 s came out 57
    frames each instead of 56, and the montage ran 100 ms long.

    ``fps`` is applied after *every* ``setpts``, including the last one.
    Resetting timestamps leaves the stream with no declared frame rate, and
    ``xfade`` rejects that outright with "current rate of 1/0 is invalid".
    The first ``fps`` is what makes the frame-count trim meaningful; the
    trailing one re-declares the rate that the trailing ``setpts`` just
    erased.
    """
    w, h = cfg.width, cfg.height
    frames = max(1, round((shot.duration or 0.0) * fps))
    # Cover-scale to the punched-in size, then slide the output window over
    # it. At zoom 1.0 with a centred focus the crop expression evaluates to
    # exactly the centre, which is what a bare ``crop=w:h`` already did, so
    # existing behaviour is unchanged.
    sw = int(round(w * shot.zoom / 2)) * 2
    sh = int(round(h * shot.zoom / 2)) * 2
    return (
        f"[{index}:v]"
        f"scale={sw}:{sh}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={w}:{h}:(in_w-{w})*{shot.focus_x:.4f}:(in_h-{h})*{shot.focus_y:.4f},"
        f"format=yuv420p,setsar=1,"
        f"setpts=PTS-STARTPTS,fps={fps},"
        f"trim=end_frame={frames},setpts=PTS-STARTPTS,fps={fps}"
        f"[s{index}]"
    )


def build_graph(plan: MontagePlan, cfg: EditConfig, fps: int) -> tuple[str, str]:
    """Return the filter graph and the label carrying the finished video."""
    chains = [_shot_chain(i, s, cfg, fps) for i, s in enumerate(plan.shots)]

    if len(plan.shots) == 1:
        return ";".join(chains), "s0"

    if plan.transition == "cut":
        inputs = "".join(f"[s{i}]" for i in range(len(plan.shots)))
        chains.append(f"{inputs}concat=n={len(plan.shots)}:v=1:a=0[vout]")
        return ";".join(chains), "vout"

    # Cross-fade: each xfade starts at the point where the outgoing shot
    # has played all but one transition's worth of its length. Offsets are
    # cumulative on the *output* clock, which is shorter than the sum of
    # the inputs by one transition per join.
    d = plan.transition_duration
    current = "s0"
    offset = 0.0
    for i in range(1, len(plan.shots)):
        offset += (plan.shots[i - 1].duration or 0.0) - d
        nxt = f"x{i}"
        chains.append(
            f"[{current}][s{i}]xfade=transition={plan.transition}:"
            f"duration={d:.3f}:offset={offset:.3f}[{nxt}]"
        )
        current = nxt
    return ";".join(chains), current


def render_montage(plan: MontagePlan, cfg: EditConfig, output: str | Path, *,
                   fps: int | None = None, crf: int = 10) -> Path:
    """Assemble the montage into an intermediate video (no audio)."""
    if plan.transition not in TRANSITIONS:
        raise ValueError(f"transition must be one of {TRANSITIONS}")
    if plan.transition != "cut" and plan.transition_duration <= 0:
        raise ValueError(f"{plan.transition!r} needs a transition_duration above zero")

    out = Path(output).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    rate = fps or cfg.fps

    args: list[str] = ["-y"]
    for shot in plan.shots:
        if not Path(shot.source).exists():
            raise FileNotFoundError(f"shot source not found: {shot.source}")
        # A little extra on -t so the graph always has the frames it needs
        # to trim down to; the exact cut happens in the filter chain.
        grab = (shot.duration or 0.0) + 0.5
        args += ["-ss", f"{shot.start:.3f}", "-t", f"{grab:.3f}",
                 "-i", str(shot.source)]

    graph, label = build_graph(plan, cfg, rate)
    args += [
        "-filter_complex", graph,
        "-map", f"[{label}]",
        "-an",
        "-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast",
        "-pix_fmt", "yuv420p", "-fps_mode", "cfr", "-r", str(rate),
        str(out),
    ]
    run_ffmpeg(args)
    return out


def check_sources(shots: list[Shot]) -> list[str]:
    """Warn about shots that cannot supply the footage they promise."""
    notes: list[str] = []
    for i, shot in enumerate(shots, 1):
        path = Path(shot.source)
        if not path.exists():
            notes.append(f"shot {i}: {path} does not exist")
            continue
        try:
            info = probe(path)
        except Exception as exc:                      # noqa: BLE001
            notes.append(f"shot {i}: could not probe {path.name} ({exc})")
            continue
        if not info.width or not info.height:
            notes.append(f"shot {i}: {path.name} has no video stream")
            continue
        need = shot.start + (shot.duration or 0.0)
        if info.duration and need > info.duration + 0.05:
            notes.append(
                f"shot {i}: {path.name} is {info.duration:.2f}s but the plan "
                f"needs {need:.2f}s - the tail will freeze or come up short"
            )
    return notes
