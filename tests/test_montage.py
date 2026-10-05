"""Montage assembly: cut planning, transitions and the music bed."""

from __future__ import annotations

import re
import subprocess

import pytest
from conftest import requires_ffmpeg  # noqa: F401  (fixture module on sys.path)

from viralcut.audio import build_music_chain
from viralcut.beats import BeatGrid, even_grid
from viralcut.config import EditConfig, build_config
from viralcut.ffmpeg_tool import find_ffmpeg
from viralcut.montage import (
    Shot,
    build_graph,
    check_sources,
    plan_shots,
    render_montage,
)


def grid_at(bpm: float, duration: float = 30.0) -> BeatGrid:
    return even_grid(duration, tempo=bpm)


def fast_config(**overrides):
    cfg = build_config("shorts", **overrides)
    cfg.width, cfg.height, cfg.fps = 240, 426, 30
    cfg.crf, cfg.x264_preset = 30, "ultrafast"
    cfg.max_bitrate, cfg.bufsize = "8M", "16M"
    cfg.loudnorm_passes = 1
    return cfg


def media_duration(path) -> float:
    out = subprocess.run([str(find_ffmpeg()), "-hide_banner", "-i", str(path)],
                         capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    assert m, f"no duration in:\n{out[-400:]}"
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def frame_count(path) -> int:
    out = subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-i", str(path), "-map", "0:v",
         "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.findall(r"frame=\s*(\d+)", out)
    assert m, "no frame count reported"
    return int(m[-1])


# --- planning -------------------------------------------------------------

def test_shots_get_a_bar_each_by_default():
    grid = grid_at(120.0)                   # 0.5 s per beat
    plan = plan_shots([Shot("a.mp4"), Shot("b.mp4")], grid, beats_per_shot=4)
    assert [s.duration for s in plan.shots] == pytest.approx([2.0, 2.0])
    assert plan.cut_times == pytest.approx([2.0, 4.0])


def test_cut_density_follows_beats_per_shot():
    grid = grid_at(120.0)
    fast = plan_shots([Shot("a.mp4")] * 4, grid, beats_per_shot=2)
    slow = plan_shots([Shot("a.mp4")] * 4, grid, beats_per_shot=8)
    assert fast.duration == pytest.approx(4.0)
    assert slow.duration == pytest.approx(16.0)


def test_an_explicit_duration_is_left_alone():
    grid = grid_at(120.0)
    plan = plan_shots([Shot("a.mp4"), Shot("b.mp4", duration=3.0), Shot("c.mp4")],
                      grid, beats_per_shot=4)
    assert plan.shots[1].duration == pytest.approx(3.0)
    assert plan.shots[0].duration == pytest.approx(2.0)


def test_frame_quantisation_stops_rounding_from_accumulating():
    """The bug this guards: ffmpeg rounds every shot up to a whole frame
    independently, so without quantised cut points the montage slides off
    the beat - 82 ms by the fourth shot at 30 fps."""
    grid = grid_at(128.0)                   # 0.46875 s per beat, not frame-aligned
    plan = plan_shots([Shot("a.mp4")] * 6, grid, beats_per_shot=4, fps=30)
    for shot in plan.shots:
        frames = shot.duration * 30
        assert abs(frames - round(frames)) < 1e-6, "shot is not a whole number of frames"
    # Total must not drift from the musical length.
    assert plan.duration == pytest.approx(6 * 4 * 60 / 128, abs=0.05)


def test_transition_lengthens_shots_but_not_the_montage():
    grid = grid_at(120.0)
    plain = plan_shots([Shot("a.mp4")] * 3, grid, beats_per_shot=4)
    faded = plan_shots([Shot("a.mp4")] * 3, grid, beats_per_shot=4,
                       transition_duration=0.4)
    faded.transition, faded.transition_duration = "fade", 0.4
    # Each shot carries an extra transition's worth of footage ...
    assert faded.shots[0].duration == pytest.approx(plain.shots[0].duration + 0.4)
    # ... which the overlaps consume, so the visible length is unchanged.
    assert faded.duration == pytest.approx(plain.duration)


def test_max_duration_truncates_the_shot_list():
    grid = grid_at(120.0)
    plan = plan_shots([Shot("a.mp4")] * 10, grid, beats_per_shot=4, max_duration=5.0)
    assert plan.duration <= 5.0 + 1e-6
    assert len(plan.shots) < 10


def test_planning_rejects_nonsense():
    grid = grid_at(120.0)
    with pytest.raises(ValueError, match="at least one shot"):
        plan_shots([], grid)
    with pytest.raises(ValueError, match="beats_per_shot"):
        plan_shots([Shot("a.mp4")], grid, beats_per_shot=0)
    with pytest.raises(ValueError, match="negative"):
        Shot("a.mp4", start=-1.0)
    with pytest.raises(ValueError, match="positive"):
        Shot("a.mp4", duration=0.0)


# --- graph construction ---------------------------------------------------

def test_hard_cuts_use_concat_and_crossfades_use_xfade():
    cfg = fast_config()
    grid = grid_at(120.0)
    shots = [Shot("a.mp4"), Shot("b.mp4"), Shot("c.mp4")]

    cut = plan_shots(shots, grid, fps=30)
    graph, label = build_graph(cut, cfg, 30)
    assert "concat=n=3" in graph
    assert "xfade" not in graph
    assert label == "vout"

    fade = plan_shots(shots, grid, transition_duration=0.3, fps=30)
    fade.transition, fade.transition_duration = "fade", 0.3
    graph, label = build_graph(fade, cfg, 30)
    assert graph.count("xfade") == 2, "two joins between three shots"
    assert "concat" not in graph
    assert label == "x2"


def test_crossfade_offsets_are_cumulative():
    """Each xfade starts one transition before the outgoing shot ends."""
    cfg = fast_config()
    plan = plan_shots([Shot("a.mp4")] * 3, grid_at(120.0),
                      transition_duration=0.5, fps=30)
    plan.transition, plan.transition_duration = "fade", 0.5
    graph, _ = build_graph(plan, cfg, 30)
    offsets = [float(x) for x in re.findall(r"offset=([\d.]+)", graph)]
    # Shots are 2.0 s visible, so joins land at 2.0 and 4.0.
    assert offsets == pytest.approx([2.0, 4.0], abs=0.05)
    assert offsets[1] > offsets[0], "offsets must advance"


def test_shot_chain_reestablishes_frame_rate_after_setpts():
    """xfade refuses a stream with no declared rate ("current rate of 1/0")."""
    cfg = fast_config()
    plan = plan_shots([Shot("a.mp4"), Shot("b.mp4")], grid_at(120.0),
                      transition_duration=0.3, fps=30)
    plan.transition, plan.transition_duration = "fade", 0.3
    graph, _ = build_graph(plan, cfg, 30)
    for chain in graph.split(";"):
        if "setpts" in chain and "xfade" not in chain:
            assert chain.rstrip("[s0123456789]").endswith(f"fps={cfg.fps or 30}") or \
                   re.search(r"setpts=PTS-STARTPTS,fps=\d+", chain), \
                   f"chain must re-declare its rate: {chain}"


def test_unknown_transition_is_rejected(tmp_path):
    plan = plan_shots([Shot("a.mp4")], grid_at(120.0))
    plan.transition = "swirl-o-matic"
    with pytest.raises(ValueError, match="transition must be one of"):
        render_montage(plan, fast_config(), tmp_path / "x.mp4")


def test_crossfade_without_a_duration_is_rejected(tmp_path):
    plan = plan_shots([Shot("a.mp4")], grid_at(120.0))
    plan.transition = "fade"
    with pytest.raises(ValueError, match="transition_duration"):
        render_montage(plan, fast_config(), tmp_path / "x.mp4")


def test_check_sources_reports_missing_and_short_files(portrait_clip):
    notes = check_sources([Shot("/nope/missing.mp4", duration=1.0)])
    assert notes and "does not exist" in notes[0]

    # portrait_clip is 2 s; ask for 10.
    notes = check_sources([Shot(portrait_clip, duration=10.0)])
    assert notes and "come up short" in notes[0]

    assert check_sources([Shot(portrait_clip, duration=1.0)]) == []


# --- rendering ------------------------------------------------------------

@requires_ffmpeg
def test_hard_cut_montage_is_frame_exact(portrait_clip, landscape_clip, tmp_path):
    cfg = fast_config()
    plan = plan_shots([Shot(portrait_clip), Shot(landscape_clip), Shot(portrait_clip)],
                      grid_at(120.0), beats_per_shot=2, fps=30)
    out = render_montage(plan, cfg, tmp_path / "cut.mp4", fps=30)

    assert frame_count(out) == round(plan.duration * 30)
    assert abs(media_duration(out) - plan.duration) < 0.02


@requires_ffmpeg
def test_crossfade_actually_blends(flat_clip, landscape_clip, tmp_path):
    """A transition that silently degrades to a hard cut would still produce
    a file of the right length, so the blend itself has to be measured."""
    cfg = fast_config()
    plan = plan_shots([Shot(flat_clip), Shot(landscape_clip)],
                      grid_at(120.0), beats_per_shot=2, transition_duration=0.4,
                      fps=30)
    plan.transition, plan.transition_duration = "fade", 0.4
    out = render_montage(plan, cfg, tmp_path / "fade.mp4", fps=30)

    def grey(t: float) -> float:
        raw = subprocess.run(
            [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error",
             "-i", str(out), "-ss", f"{t}", "-frames:v", "1",
             "-vf", "format=gray", "-f", "rawvideo", "-"],
            capture_output=True, check=True).stdout
        assert raw, f"no frame at {t}"
        return sum(raw) / len(raw)

    # The join sits at 1.0 s and lasts 0.4 s.
    before, middle, after = grey(0.6), grey(1.2), grey(1.8)
    assert abs(middle - before) > 1.0, "no visible change mid-transition"
    assert abs(after - middle) > 1.0, "transition never completed"


@requires_ffmpeg
def test_montage_scales_mixed_sources_to_one_canvas(portrait_clip, landscape_clip, tmp_path):
    cfg = fast_config()
    plan = plan_shots([Shot(landscape_clip), Shot(portrait_clip)],
                      grid_at(120.0), beats_per_shot=2, fps=30)
    out = render_montage(plan, cfg, tmp_path / "mixed.mp4", fps=30)
    info = subprocess.run([str(find_ffmpeg()), "-hide_banner", "-i", str(out)],
                          capture_output=True, text=True).stderr
    assert f"{cfg.width}x{cfg.height}" in info


@requires_ffmpeg
def test_missing_shot_source_raises(tmp_path):
    plan = plan_shots([Shot(tmp_path / "ghost.mp4")], grid_at(120.0), fps=30)
    with pytest.raises(FileNotFoundError, match="shot source not found"):
        render_montage(plan, fast_config(), tmp_path / "out.mp4", fps=30)


# --- music ----------------------------------------------------------------

def test_music_chain_loops_trims_and_fades():
    cfg = EditConfig()
    cfg.music_fade_in, cfg.music_fade_out = 0.25, 0.6
    chain = ",".join(build_music_chain(cfg, 10.0))
    assert "aloop=loop=-1" in chain, "a short track must repeat, not fall silent"
    assert "atrim=end=10.000" in chain
    assert "afade=t=in:st=0:d=0.250" in chain
    assert "afade=t=out:st=9.400:d=0.600" in chain


def test_music_fades_cannot_overlap_on_a_short_cut():
    cfg = EditConfig()
    cfg.music_fade_in, cfg.music_fade_out = 5.0, 5.0
    chain = ",".join(build_music_chain(cfg, 2.0))
    assert "afade=t=in:st=0:d=1.000" in chain
    assert "afade=t=out:st=1.000:d=1.000" in chain


def test_music_start_trims_the_head():
    cfg = EditConfig()
    cfg.music_start = 12.5
    chain = ",".join(build_music_chain(cfg, 8.0))
    assert "atrim=start=12.500" in chain


def test_two_pass_music_normalisation_shifts_with_gain():
    """Gain is a linear scaling, so the measured figures move with it
    exactly - re-measuring after applying gain would be wasted work."""
    cfg = EditConfig()
    cfg.music_gain = 3.0
    measured = {"input_i": "-20.00", "input_tp": "-2.00", "input_lra": "5.0",
                "input_thresh": "-30.00", "target_offset": "0.0"}
    chain = ",".join(build_music_chain(cfg, 10.0, measured))
    assert "measured_I=-17.0" in chain
    assert "measured_TP=1.0" in chain
    assert "linear=true" in chain


def test_music_falls_back_to_single_pass_without_measurement():
    cfg = EditConfig()
    chain = ",".join(build_music_chain(cfg, 10.0, None))
    assert "loudnorm=I=-14.0:TP=-1.0:LRA=11" in chain
    assert "measured_I" not in chain


def test_music_config_is_validated():
    cfg = EditConfig()
    cfg.music_mode = "sideways"
    with pytest.raises(ValueError, match="music_mode"):
        cfg.validate()
    cfg = EditConfig()
    cfg.music_start = -1.0
    with pytest.raises(ValueError, match="music_start"):
        cfg.validate()
