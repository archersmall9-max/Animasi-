from __future__ import annotations

from conftest import requires_ffmpeg  # noqa: F401

from viralcut.analyze import Analysis, analyze, measure_loudness_curve, score_windows
from viralcut.probe import MediaInfo


def fake(duration: float = 60.0) -> Analysis:
    info = MediaInfo(path="x", width=1920, height=1080, fps=30, duration=duration, has_audio=True)
    return Analysis(info=info)


def test_scoring_prefers_busy_loud_sections():
    a = fake()
    a.scene_cuts = [31.0, 32.5, 34.0, 36.0, 38.5, 41.0, 43.0, 45.0]
    a.loudness = [(float(t), -12.0 if 30 <= t <= 45 else -35.0) for t in range(0, 60)]
    scores = score_windows(a, window=15.0, step=1.0)
    best = max(scores, key=lambda s: s[1])[0]
    assert 28.0 <= best <= 34.0


def test_scoring_breaks_ties_towards_the_start():
    a = fake()
    a.loudness = [(float(t), -20.0) for t in range(0, 60)]
    scores = score_windows(a, window=15.0, step=1.0)
    assert max(scores, key=lambda s: s[1])[0] == 0.0


def test_short_sources_are_not_trimmed():
    a = fake(duration=10.0)
    assert score_windows(a, window=30.0) == [(0.0, 1.0)]


@requires_ffmpeg
def test_loudness_curve_has_points(landscape_clip):
    curve = measure_loudness_curve(landscape_clip)
    assert len(curve) > 5
    assert all(isinstance(t, float) and isinstance(m, float) for t, m in curve)
    assert max(m for _, m in curve) > -40


@requires_ffmpeg
def test_analyze_runs_end_to_end(landscape_clip):
    result = analyze(landscape_clip)
    assert result.info.duration > 0
    assert "source" in result.summary()
    # 2 s clip, 15 s minimum window -> nothing to choose from
    assert result.best_window is None
