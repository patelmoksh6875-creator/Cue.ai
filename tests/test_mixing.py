import numpy as np
import pytest

import config
from mixing import align, render, styles


# --- snippet cache keys ------------------------------------------------


def test_snippet_cache_key_includes_analyzer_version():
    key = render.snippet_cache_key(1, 2, "blend", 12)
    assert key == f"1_2_blend_12_auto_w0_{config.ANALYZER_VERSION}"


def test_snippet_cache_key_distinguishes_style_and_length():
    a = render.snippet_cache_key(1, 2, "blend", 12)
    b = render.snippet_cache_key(1, 2, "cut", 12)
    c = render.snippet_cache_key(1, 2, "blend", 15)
    d = render.snippet_cache_key(1, 2, "blend", 12, source="beat_view")
    e = render.snippet_cache_key(1, 2, "blend", 12, window_rank=1)
    assert len({a, b, c, d, e}) == 5


def test_snippet_path_lives_under_snippet_dir():
    path = render.snippet_path("abc123")
    assert path.parent == render.SNIPPET_DIR
    assert path.name == "abc123.mp3"


# --- plan_tempo_match --------------------------------------------------


def test_plan_tempo_match_exact():
    plan = align.plan_tempo_match(128, 128)
    assert plan.stretch_ratio == pytest.approx(1.0)
    assert not plan.used_half_double
    assert not plan.exceeds_quality_threshold


def test_plan_tempo_match_exact_double_time_needs_no_stretch():
    # A candidate at exactly half the seed's BPM is already in a valid
    # half-time relationship -- no stretching needed, just flagged.
    plan = align.plan_tempo_match(128, 64)
    assert plan.stretch_ratio == pytest.approx(1.0)
    assert plan.used_half_double


def test_plan_tempo_match_exact_half_time_needs_no_stretch():
    plan = align.plan_tempo_match(64, 128)
    assert plan.stretch_ratio == pytest.approx(1.0)
    assert plan.used_half_double


def test_plan_tempo_match_near_double_time_needs_small_stretch():
    # Candidate close to (but not exactly) double-time of the seed still
    # prefers the half/double option, with a small corrective stretch.
    plan = align.plan_tempo_match(128, 63)
    assert plan.used_half_double
    assert plan.stretch_ratio == pytest.approx(128 / 126, abs=1e-4)


def test_plan_tempo_match_flags_large_stretch():
    plan = align.plan_tempo_match(128, 110)
    assert plan.exceeds_quality_threshold
    assert plan.stretch_pct > align.MAX_CLEAN_STRETCH_PCT


def test_plan_tempo_match_small_stretch_ok():
    plan = align.plan_tempo_match(128, 125)
    assert not plan.exceeds_quality_threshold


# --- time_stretch --------------------------------------------------------


def test_time_stretch_noop_at_ratio_one():
    y = np.random.RandomState(0).randn(4096).astype(np.float32)
    out = align.time_stretch(y, 1.0)
    assert np.array_equal(y, out)


def test_time_stretch_changes_length():
    sr = 22050
    y = np.sin(2 * np.pi * 220 * np.arange(sr) / sr).astype(np.float32)
    out = align.time_stretch(y, 2.0)
    assert len(out) < len(y)  # sped up -> shorter


# --- styles: all return the expected length and stay finite -----------------


def _sine(freq, sr, seconds):
    t = np.arange(int(sr * seconds)) / sr
    return np.sin(2 * np.pi * freq * t).astype(np.float32)


@pytest.mark.parametrize("style_name", ["blend", "cut", "echo-out"])
def test_style_returns_finite_same_length_audio(style_name):
    sr = 22050
    a = _sine(220, sr, 2.0)
    b = _sine(330, sr, 2.0)
    style_fn = styles.STYLES[style_name]
    out = style_fn(a, b, sr)
    assert len(out) == min(len(a), len(b))
    assert np.all(np.isfinite(out))


def test_blend_crossfade_starts_near_a_ends_near_b():
    sr = 22050
    a = np.ones(sr, dtype=np.float32) * 0.5
    b = np.ones(sr, dtype=np.float32) * -0.5
    out = styles.blend(a, b, sr)
    # Near the start, A should dominate; near the end, B should dominate.
    assert out[10] > 0
    assert out[-10] < 0


def test_cut_is_a_then_b_with_no_nans():
    sr = 22050
    a = np.ones(sr, dtype=np.float32)
    b = np.ones(sr, dtype=np.float32) * -1.0
    out = styles.cut(a, b, sr)
    assert out[0] == pytest.approx(1.0)
    assert out[-1] == pytest.approx(-1.0)
    assert np.all(np.isfinite(out))


# ---- synthetic click tracks: known tempo and offset --------------------------
from mixing import beatview, windows  # noqa: E402

SR = 22050


def click_track(bpm, seconds, offset_s=0.0):
    y = np.zeros(int(SR * seconds), dtype=np.float32)
    beat = 60.0 / bpm
    t = offset_s
    burst = np.sin(2 * np.pi * 60 * np.arange(int(0.05 * SR)) / SR).astype(np.float32) * np.hanning(int(0.05 * SR))
    while t < seconds - 0.1:
        i = int(t * SR)
        y[i : i + len(burst)] += burst
        t += beat
    return y


def test_best_beat_offset_finds_known_offset():
    a = click_track(120, 8, 0.0)
    b = click_track(120, 8, 0.2)
    beats_b = np.arange(0.2, 8, 0.5)
    off = align.best_beat_offset(a, b, SR, beats_b)
    # B's beats sit 0.2s late; starting B on one of its own beats keeps the grids locked.
    assert any(abs(off - bt) < 0.03 for bt in beats_b[:4])


def test_window_ranking_locks_a_shifted_click_track():
    a = click_track(120, 20, 0.0)
    b = click_track(120, 20, 0.15)  # same tempo, kicks 150 ms late
    beats_a = np.arange(0, 20, 0.5)
    beats_b = np.arange(0.15, 20, 0.5)
    cands = windows.rank_windows(a, b, SR, beats_a, beats_b, blend_s=6.0, lead_s=3.0, tail_s=3.0, bpm=120)
    assert cands and cands[0].drum_corr > 0.8
    # B's kicks are 150 ms late, so the kicks coincide when B's window starts
    # 150 ms (mod one beat) after A's -- within 40 ms.
    delta = (cands[0].b_blend_start - cands[0].a_blend_start) % 0.5
    assert min(abs(delta - 0.15), abs(delta - 0.15 + 0.5), abs(delta - 0.15 - 0.5)) < 0.04


def test_window_ranking_returns_distinct_candidates():
    a = click_track(120, 25)
    b = click_track(120, 25)
    cands = windows.rank_windows(a, b, SR, np.arange(0, 25, 0.5), np.arange(0, 25, 0.5), 6.0, 3.0, 3.0, 120)
    assert 1 < len(cands) <= 3
    for i, c in enumerate(cands):
        for d in cands[i + 1:]:
            assert abs(c.a_blend_start - d.a_blend_start) >= 2.5 or abs(c.b_blend_start - d.b_blend_start) >= 2.5


def test_window_ranking_empty_when_clip_too_short():
    short = click_track(120, 5)
    assert windows.rank_windows(short, short, SR, np.arange(0, 5, 0.5), np.arange(0, 5, 0.5), 6.0, 3.0, 3.0, 120) == []


def test_beat_interval_cv_detects_tempo_change():
    steady = np.arange(0, 10, 0.5)
    changing = np.concatenate([np.arange(0, 5, 0.5), 5 + np.arange(0, 5, 0.3)])
    assert windows.beat_interval_cv(steady, 0, 10) < 0.01
    assert windows.beat_interval_cv(changing, 0, 10) > 0.1
    assert windows.beat_interval_cv(steady, 0, 1) is None  # too few beats


def test_blend_length_is_whole_beats_and_fits():
    assert render.blend_beats_for(120, 12) == 8      # 16 beats = 8s > 60% of 12s
    assert render.blend_beats_for(160, 15) == 16     # 16 beats = 6s fits
    assert render.blend_beats_for(60, 10) == 4


def test_beat_view_keeps_kick_and_stays_finite():
    y = click_track(120, 6)
    out = beatview.make_beat_view(y, SR, add_low_end=True, low_end_hz=120)
    assert np.all(np.isfinite(out)) and np.max(np.abs(out)) <= 1.0 and len(out) == len(y)
    no_low = beatview.make_beat_view(y, SR, add_low_end=False)
    assert np.sqrt(np.mean(out**2)) >= np.sqrt(np.mean(no_low**2)) * 0.9


def test_grid_overlap_and_drift_helpers():
    g = np.arange(0, 10, 0.5)
    assert render._grid_overlap(g, g + 0.01) == 1.0
    assert render._grid_overlap(g, g + 0.25) == 0.0
    assert render._half_tempo_drift(g) < 0.01
