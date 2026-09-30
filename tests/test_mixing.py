import numpy as np
import pytest

from mixing import align, styles


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
