"""Beat tracking, checked against patterns whose true beats are known.

Everything is synthesised here, so the answer is not a matter of opinion:
the kick is written at an exact sample, and the tracker either finds it or
it does not.
"""

from __future__ import annotations

import numpy as np
import pytest

from viralcut.beats import (
    ANALYSIS_RATE,
    BeatGrid,
    estimate_tempo,
    even_grid,
    load_audio,
    onset_envelopes,
    track_beats,
)

SR = ANALYSIS_RATE


def drum_loop(bpm: float, duration: float = 20.0, pattern: str = "four",
              rate: int = SR) -> np.ndarray:
    """A drum pattern with the beats at known sample positions.

    ``four``     kick on every beat, hats on the offbeats
    ``backbeat`` kick on 1 and 3, snare on 2 and 4, hats on the offbeats
    """
    n = int(duration * rate)
    y = np.zeros(n, dtype=np.float32)
    period = 60.0 / bpm

    t = np.arange(int(0.08 * rate)) / rate
    kick = (np.sin(2 * np.pi * 55 * t) * np.exp(-t * 35)).astype(np.float32)
    rng = np.random.default_rng(2)
    snare = (rng.standard_normal(int(0.05 * rate))
             * np.exp(-np.arange(int(0.05 * rate)) / rate * 60)).astype(np.float32) * 0.5
    hat = (np.random.default_rng(0).standard_normal(int(0.03 * rate))
           * np.exp(-np.arange(int(0.03 * rate)) / rate * 120)).astype(np.float32) * 0.3

    k = 0
    while k * period < duration:
        i = int(k * period * rate)
        if pattern == "backbeat":
            if k % 4 in (0, 2):
                y[i:i + len(kick)] += kick
            elif i + len(snare) < n:
                y[i:i + len(snare)] += snare
        else:
            y[i:i + len(kick)] += kick * (1.0 if k % 4 == 0 else 0.7)
        j = int((k + 0.5) * period * rate)
        if j + len(hat) < n:
            y[j:j + len(hat)] += hat
        k += 1

    return y + np.random.default_rng(1).standard_normal(n).astype(np.float32) * 0.002


def beat_error(grid: BeatGrid, bpm: float, duration: float = 20.0) -> np.ndarray:
    """Distance from each detected beat to the nearest true beat."""
    found = np.asarray(grid.beats)
    truth = np.arange(0.0, duration, 60.0 / bpm)
    return np.abs(found[:, None] - truth[None, :]).min(axis=1)


# --- the thing that actually matters -------------------------------------

@pytest.mark.parametrize("bpm", [90, 100, 120, 128, 140, 150, 160, 174])
@pytest.mark.parametrize("pattern", ["four", "backbeat"])
def test_beats_land_on_the_beat(bpm, pattern):
    """Every detected beat must sit on a real one.

    This is the property a cut depends on. The reported tempo may come out
    an octave low on some patterns - a half-time grid is a subset of the
    real beats, so the cuts are sparser but still locked - and that is
    checked separately and more loosely below.
    """
    grid = track_beats(drum_loop(bpm, pattern=pattern))
    err = beat_error(grid, bpm)
    assert len(grid.beats) > 10
    assert err.mean() < 0.040, f"mean {err.mean() * 1000:.0f} ms off the beat"
    assert np.percentile(err, 90) < 0.060


@pytest.mark.parametrize("bpm", [100, 120, 128, 140, 174])
def test_tempo_is_right_or_an_octave_out(bpm):
    """Tempo must be the real one, or a clean half or double of it."""
    grid = track_beats(drum_loop(bpm, pattern="four"))
    ratio = grid.tempo / bpm
    assert any(abs(ratio - r) < 0.04 for r in (0.5, 1.0, 2.0)), \
        f"{grid.tempo:.1f} is not a musical relative of {bpm}"


def test_four_on_the_floor_gets_the_tempo_exactly():
    """With a kick on every beat there is no excuse for an octave error."""
    for bpm in (100, 120, 128, 140, 174):
        grid = track_beats(drum_loop(bpm, pattern="four"))
        assert abs(grid.tempo - bpm) < 4.0, f"{grid.tempo:.1f} should be {bpm}"


def test_offbeat_hats_do_not_capture_the_grid():
    """The regression that made every cut feel half a beat late.

    Hi-hats are broadband and produce far more spectral flux than the kick,
    so a tracker that scores on raw flux locks onto the offbeats.
    """
    bpm = 120.0
    grid = track_beats(drum_loop(bpm, pattern="four"))
    half_beat = 60.0 / bpm / 2.0
    err = beat_error(grid, bpm)
    assert err.mean() < half_beat * 0.25, "grid drifted towards the offbeat hats"


def test_low_band_envelope_favours_the_kick():
    """The beat envelope must rate a kick above a hi-hat; the tempo one need not."""
    y = drum_loop(120.0, pattern="four")
    tempo_env, beat_env = onset_envelopes(y)
    fps = SR / 256
    kicks = [int(round(t * fps)) for t in np.arange(0.5, 19.0, 0.5)]
    hats = [int(round(t * fps)) for t in np.arange(0.75, 19.0, 0.5)]
    assert beat_env[kicks].mean() > beat_env[hats].mean() * 1.3
    assert len(tempo_env) == len(beat_env)


# --- grid arithmetic ------------------------------------------------------

def test_grid_helpers():
    grid = BeatGrid(tempo=120.0, beats=tuple(i * 0.5 for i in range(9)),
                    downbeats=(0.0, 2.0, 4.0), confidence=0.9, duration=4.5)
    assert grid.period == pytest.approx(0.5)
    assert grid.nearest(1.26) == pytest.approx(1.5)
    assert grid.snap(1.46) == pytest.approx(1.5), "within tolerance, should snap"
    assert grid.snap(1.20) == pytest.approx(1.20), "outside tolerance, should not move"
    assert grid.after(1.5) == pytest.approx(2.0)
    assert grid.after(99.0) == pytest.approx(99.0), "past the end, returns the input"
    assert grid.every(4) == pytest.approx([0.0, 2.0, 4.0])
    # every() keeps the global phase: it filters the real beat sequence
    # rather than re-counting from `start`, so a cut list stays on the bar.
    assert grid.every(2, start=1.0) == pytest.approx([1.0, 2.0, 3.0, 4.0])
    with pytest.raises(ValueError):
        grid.every(0)


def test_even_grid_is_a_usable_fallback():
    grid = even_grid(4.0, tempo=120.0)
    assert grid.tempo == 120.0
    assert grid.beats[:3] == pytest.approx([0.0, 0.5, 1.0])
    assert grid.confidence == 0.0, "a made-up grid must not claim confidence"


def test_downbeats_are_a_subset_spaced_by_four():
    grid = track_beats(drum_loop(120.0, pattern="four"))
    assert len(grid.downbeats) >= 4
    assert set(grid.downbeats) <= set(grid.beats)
    gaps = np.diff(grid.downbeats)
    assert np.allclose(gaps, gaps[0], atol=0.05)
    assert gaps[0] == pytest.approx(grid.period * 4, rel=0.1)


# --- edges ---------------------------------------------------------------

def test_silence_and_very_short_input_do_not_crash():
    quiet = track_beats(np.zeros(SR * 3, dtype=np.float32))
    assert quiet.beats == () or quiet.tempo == 0.0

    tiny = track_beats(np.zeros(SR // 4, dtype=np.float32))
    assert tiny.beats == ()
    assert tiny.tempo == 0.0


def test_tempo_of_an_empty_envelope_is_zero():
    assert estimate_tempo(np.zeros(3)) == 0.0


def test_load_audio_rejects_a_file_with_no_audio(tmp_path):
    bad = tmp_path / "not-audio.bin"
    bad.write_bytes(b"this is not a media file")
    with pytest.raises(ValueError, match="no decodable audio"):
        load_audio(bad)


def test_confidence_separates_a_real_track_from_noise():
    real = track_beats(drum_loop(128.0, pattern="four"))
    noise = track_beats(
        np.random.default_rng(7).standard_normal(SR * 15).astype(np.float32) * 0.1
    )
    assert real.confidence > noise.confidence
