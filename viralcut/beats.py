"""Beat tracking, so cuts can land on the music instead of near it.

An anime edit lives or dies on whether the cuts hit. "Close enough" reads as
sloppy: the ear notices a cut that is 80 ms early far more readily than the
eye notices a slightly odd framing. So the editor needs to know where the
beats actually are before it decides where to cut.

Why this is written by hand rather than pulled from a library: ``librosa``
would do all of this and more, but it drags in scipy, numba and llvmlite —
roughly 200 MB of wheels, a long cold install on a CI runner, and a
toolchain that breaks on Python upgrades. What an edit needs is a tempo, a
beat grid and a downbeat phase. That is a few hundred lines of numpy.

The approach is the standard one:

1. decode to mono at a low sample rate — beat tracking does not need 48 kHz
2. short-time Fourier transform, log-compressed
3. spectral flux: how much energy *appeared* between frames, which is what a
   drum hit looks like in the frequency domain
4. autocorrelate that envelope to find the tempo
5. slide a constant-tempo grid over the envelope and keep the phase with the
   most energy under it
6. pick the downbeat phase the same way, over bars of four

Constant tempo is an assumption, and it is the right one here: tracks chosen
for a 15–30 second edit are machine-timed. There is a sanity check for
tracks that drift, and ``BeatGrid.confidence`` says how well the grid fits
so a caller can fall back to even spacing.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .ffmpeg_tool import find_ffmpeg

log = logging.getLogger(__name__)

# 22.05 kHz keeps everything a drum transient needs (the top octave of a
# cymbal is detail we are throwing away anyway) at a quarter of the samples.
ANALYSIS_RATE = 22050
N_FFT = 1024
HOP = 256                      # 11.6 ms at 22.05 kHz — finer than any cut needs
BPM_RANGE = (60.0, 200.0)      # below is a half-time reading, above is double


@dataclass(frozen=True)
class BeatGrid:
    """Where the beats are, and how much to trust that."""

    tempo: float               # BPM
    beats: tuple[float, ...]   # seconds from the start of the track
    downbeats: tuple[float, ...]   # first beat of each bar of four
    confidence: float          # 0–1, how much onset energy sits on the grid
    duration: float            # seconds of audio analysed

    @property
    def period(self) -> float:
        """Seconds per beat."""
        return 60.0 / self.tempo if self.tempo > 0 else 0.0

    def nearest(self, t: float) -> float:
        """The beat closest to ``t``. Used to snap a cut that is nearly right."""
        if not self.beats:
            return t
        arr = np.asarray(self.beats)
        return float(arr[int(np.argmin(np.abs(arr - t)))])

    def snap(self, t: float, tolerance: float = 0.12) -> float:
        """Snap ``t`` to a beat, but only if one is within ``tolerance``.

        A cut deliberately placed off the grid stays where it was put.
        """
        b = self.nearest(t)
        return b if abs(b - t) <= tolerance else t

    def after(self, t: float) -> float:
        """The first beat strictly after ``t`` (or ``t`` if the grid ran out)."""
        later = [b for b in self.beats if b > t + 1e-6]
        return later[0] if later else t

    def every(self, n: int, start: float = 0.0) -> list[float]:
        """Every ``n``-th beat from ``start`` — the usual source of cut points."""
        if n < 1:
            raise ValueError("n must be at least 1")
        return [b for i, b in enumerate(self.beats) if b >= start and i % n == 0]


def load_audio(path: str | Path, rate: int = ANALYSIS_RATE) -> np.ndarray:
    """Decode any input to a mono float32 waveform in [-1, 1]."""
    proc = subprocess.run(
        [str(find_ffmpeg()), "-hide_banner", "-loglevel", "error",
         "-i", str(path), "-vn", "-ac", "1", "-ar", str(rate),
         "-f", "f32le", "-"],
        capture_output=True, check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ValueError(f"no decodable audio in {path}: {err[-1] if err else 'empty'}")
    return np.frombuffer(proc.stdout, dtype=np.float32)


def _stft_magnitude(y: np.ndarray, n_fft: int = N_FFT, hop: int = HOP) -> np.ndarray:
    """Magnitude spectrogram, frames on axis 0."""
    # Centred framing: pad by half a window so frame i sits at time
    # i*hop/sr. Without this every onset reads about 23 ms late, which is
    # exactly the kind of error that makes cuts feel behind the music.
    y = np.pad(y, (n_fft // 2, n_fft // 2))
    if len(y) < n_fft:
        y = np.pad(y, (0, n_fft - len(y)))
    n_frames = 1 + (len(y) - n_fft) // hop
    window = np.hanning(n_fft).astype(np.float32)
    # One strided gather beats a Python loop by a wide margin here.
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n_frames)[:, None]
    frames = y[idx] * window
    return np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32)


def _post(env: np.ndarray) -> np.ndarray:
    """Local-mean subtraction and normalisation, shared by both envelopes."""
    env = np.concatenate([[0.0], env])
    if len(env) > 16:
        kernel = np.ones(16, dtype=np.float32) / 16.0
        env = np.maximum(env - np.convolve(env, kernel, mode="same"), 0.0)
    peak = env.max()
    return env / peak if peak > 0 else env


def onset_envelopes(y: np.ndarray, hop: int = HOP, n_fft: int = N_FFT,
                    rate: int = ANALYSIS_RATE,
                    low_weight: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    """Two onset envelopes: one for *how fast*, one for *exactly when*.

    They are separated because the two questions have different best
    answers, and using one envelope for both gets one of them wrong.

    **Tempo envelope** — full band, log-compressed. Every onset counts
    equally, so the beat rate is whatever is densest. This has to be the
    tempo source: drum patterns routinely put the kick on beats 1 and 3
    only, and a kick-weighted envelope then reports half the real tempo.
    That octave error is not academic — it was happening on every track
    above 140 BPM, where half-time still lands inside the plausible range.

    **Beat envelope** — the same, plus a heavy vote from linear sub-120 Hz
    flux. This is a kick detector, and it decides *phase*. Without it the
    tracker locks onto offbeat hi-hats: broadband noise lights up every bin
    at once and outweighs the kick roughly 8:1 in full-band flux, giving
    the right tempo half a beat late. Linear matters as much as low —
    log compression squashes the kick's 25x amplitude advantage to about
    2x. On a synthetic pattern, linear low-band flux puts the kick 43x
    above the hat; log-compressed, 1.5x.

    Only increases count in both: energy dying away is a note ending, not
    an onset, and counting it would smear the envelope.
    """
    mag = _stft_magnitude(y, n_fft=n_fft, hop=hop)

    full = np.maximum(np.diff(np.log1p(mag * 8.0), axis=0), 0.0).sum(axis=1)
    n_low = max(1, int(round(120.0 * n_fft / rate)))
    low = np.maximum(np.diff(mag[:, :n_low], axis=0), 0.0).sum(axis=1)

    def _norm(v: np.ndarray) -> np.ndarray:
        peak = v.max()
        return v / peak if peak > 0 else v

    full_n, low_n = _norm(full), _norm(low)
    return _post(full_n), _post(full_n + low_weight * low_n)


def onset_strength(y: np.ndarray, hop: int = HOP, n_fft: int = N_FFT,
                   rate: int = ANALYSIS_RATE, low_weight: float = 2.0) -> np.ndarray:
    """The beat-placement envelope. See :func:`onset_envelopes`."""
    return onset_envelopes(y, hop=hop, n_fft=n_fft, rate=rate,
                           low_weight=low_weight)[1]


def estimate_tempo(env: np.ndarray, hop: int = HOP,
                   rate: int = ANALYSIS_RATE,
                   bpm_range: tuple[float, float] = BPM_RANGE) -> float:
    """Tempo in BPM, by autocorrelating the onset envelope.

    The envelope repeats at the beat period, so its autocorrelation peaks
    there. Lags are restricted to a musical range, which also stops the
    trivial zero-lag peak from winning.
    """
    if len(env) < 4:
        return 0.0
    centred = env - env.mean()
    ac = np.correlate(centred, centred, mode="full")[len(centred) - 1:]
    if ac[0] > 0:
        ac = ac / ac[0]

    frames_per_sec = rate / hop
    lo = int(frames_per_sec * 60.0 / bpm_range[1])
    hi = int(frames_per_sec * 60.0 / bpm_range[0])
    hi = min(hi, len(ac) - 1)
    if hi <= lo:
        return 0.0

    # Comb filter, not a single peak. Autocorrelation peaks at the beat
    # period *and* at every multiple of it, and on a backbeat pattern the
    # two-beat lag often wins outright: kick-snare-kick-snare repeats more
    # exactly every two beats than every one, because consecutive beats are
    # different sounds. Scoring each candidate lag together with its own
    # multiples breaks that tie — the true period has energy at L, 2L, 3L,
    # while the doubled period only collects the even ones.
    lags = np.arange(lo, hi + 1)
    scores = np.zeros(len(lags), dtype=np.float64)
    for harmonic in (1, 2, 3, 4):
        probe = lags * harmonic
        inside = probe < len(ac)
        scores[inside] += ac[probe[inside]] / harmonic

    # Favour the middle of the range: a steady 150 BPM track is otherwise
    # just as happy to report 75.
    bpms = frames_per_sec * 60.0 / lags
    scores *= np.exp(-0.5 * (np.log2(bpms / 125.0) / 0.9) ** 2)

    return float(frames_per_sec * 60.0 / lags[int(np.argmax(scores))])


def _dp_beats(env: np.ndarray, period: float, tightness: float = 100.0) -> np.ndarray:
    """Pick the best beat sequence by dynamic programming (Ellis, 2007).

    Sliding a rigid grid over the envelope is not good enough: a 1 % tempo
    error is invisible at the start and a whole beat out by the end, and the
    best-fitting rigid phase is a compromise that fits nothing well.

    Instead every frame is scored as "onset energy here, plus the best score
    of any plausible previous beat, minus a penalty for the gap being the
    wrong length". The penalty is quadratic in log-spacing, so the sequence
    is pulled towards the estimated tempo but can breathe with the track.
    Backtracking from the best final score gives the beats.
    """
    n = len(env)
    if n < 2 or period < 1:
        return np.array([], dtype=int)

    # A beat may follow the previous one by between half and twice the period.
    offsets = np.arange(-round(2 * period), -round(period / 2) + 1)
    offsets = offsets[offsets < 0]
    if len(offsets) == 0:
        return np.array([], dtype=int)
    penalty = -tightness * (np.log(-offsets / period) ** 2)

    score = np.zeros(n, dtype=np.float64)
    backlink = np.full(n, -1, dtype=np.int64)

    for t_i in range(n):
        cand = t_i + offsets
        ok = cand >= 0
        if not ok.any():
            score[t_i] = env[t_i]
            continue
        vals = score[cand[ok]] + penalty[ok]
        best = int(np.argmax(vals))
        score[t_i] = env[t_i] + vals[best]
        backlink[t_i] = cand[ok][best]

    # Start from the best score in the final stretch, so a loud last frame
    # cannot drag the whole sequence out of alignment.
    tail = max(0, n - int(round(period)))
    end = tail + int(np.argmax(score[tail:]))

    beats = []
    while end >= 0:
        beats.append(end)
        end = int(backlink[end])
    return np.array(beats[::-1], dtype=int)


def _halve_if_double_time(env: np.ndarray, idx: np.ndarray,
                          frames_per_sec: float,
                          floor_bpm: float = BPM_RANGE[0]) -> np.ndarray:
    """Drop every other beat when the grid is counting double.

    Of the two ways a tempo estimate can land on the wrong octave, only one
    actually damages an edit. Half-time grids are a subset of the real
    beats: fewer cut points, every one of them still on a kick. Double-time
    grids alternate kick, hi-hat, kick, hi-hat — half the cut points land
    between the beats, and that is audible immediately.

    The tell is a limp every other beat, measured on the kick-weighted
    envelope where a hi-hat barely registers. Genuine accent patterns vary
    too (a four-on-the-floor track leans on beat one), so the threshold sits
    above that: 0.72 passes a 1.0 / 0.7 accent and catches a kick / hat
    alternation at 0.64.
    """
    if len(idx) < 8:
        return idx
    strengths = env[idx]
    even, odd = float(strengths[0::2].mean()), float(strengths[1::2].mean())
    strong, weak = max(even, odd), min(even, odd)
    if strong <= 0 or weak / strong > 0.72:
        return idx

    period = float(np.median(np.diff(idx)))
    if frames_per_sec * 60.0 / (period * 2.0) < floor_bpm:
        return idx          # halving would drop below a plausible tempo

    return idx[0::2] if even >= odd else idx[1::2]


def track_beats(source: str | Path | np.ndarray,
                rate: int = ANALYSIS_RATE, hop: int = HOP) -> BeatGrid:
    """Full analysis: tempo, beat grid and downbeats for a track."""
    y = source if isinstance(source, np.ndarray) else load_audio(source, rate)
    duration = len(y) / rate
    if duration < 1.0:
        return BeatGrid(0.0, (), (), 0.0, duration)

    tempo_env, env = onset_envelopes(y, hop=hop, rate=rate)
    if env.max() <= 0:
        # Digital silence, or a tone with no transients. There is nothing to
        # lock to, and inventing a grid would be worse than admitting it.
        return BeatGrid(0.0, (), (), 0.0, duration)
    # Tempo from the full-band envelope, beats from the kick-weighted one.
    tempo = estimate_tempo(tempo_env, hop=hop, rate=rate)
    if tempo <= 0:
        return BeatGrid(0.0, (), (), 0.0, duration)

    frames_per_sec = rate / hop
    period_frames = frames_per_sec * 60.0 / tempo
    idx = _dp_beats(env, period_frames)
    idx = _halve_if_double_time(env, idx, frames_per_sec)
    if len(idx) < 2:
        return BeatGrid(0.0, (), (), 0.0, duration)

    beats = tuple(float(i / frames_per_sec) for i in idx)
    # The DP result is the better tempo estimate: it is what the beats
    # actually came out as, rather than what autocorrelation guessed.
    tempo = 60.0 / float(np.median(np.diff(idx)) / frames_per_sec)

    # Downbeat: of the four bar phases, the one carrying the most energy.
    # Snares and kicks are not spread evenly across a bar.
    downbeats: tuple[float, ...] = ()
    if len(beats) >= 4:
        scores = [float(env[idx[p::4]].mean()) for p in range(4)]
        downbeats = tuple(beats[p] for p in range(int(np.argmax(scores)), len(beats), 4))

    # Confidence: normalised autocorrelation of the onset envelope at the
    # beat period - literally "does this signal repeat at this rate".
    #
    # Two more obvious measures were tried and both lie. Beat energy against
    # the track average saturates, because the dynamic programme puts beats
    # on peaks whatever it is fed, so white noise scores a perfect 1.0. Beat
    # energy against the midpoints between beats inverts the answer: a real
    # track with offbeat hi-hats has loud midpoints and scores *worse* than
    # noise. Periodicity is the property actually being claimed.
    centred = tempo_env - tempo_env.mean()
    energy = float(centred @ centred)
    lag = int(round(float(np.median(np.diff(idx)))))
    if energy > 0 and 0 < lag < len(centred):
        confidence = float(np.clip((centred[:-lag] @ centred[lag:]) / energy, 0.0, 1.0))
    else:
        confidence = 0.0
    if confidence < 0.10:
        log.warning("weak beat grid for this track (%.0f BPM, confidence %.2f) - "
                    "cuts may not feel locked", tempo, confidence)

    return BeatGrid(round(tempo, 2), beats, downbeats, round(confidence, 3), duration)


def even_grid(duration: float, tempo: float = 120.0) -> BeatGrid:
    """A synthetic grid, for when there is no music to analyse."""
    period = 60.0 / tempo
    beats = tuple(float(t) for t in np.arange(0.0, duration, period))
    return BeatGrid(tempo, beats, beats[::4], 0.0, duration)
