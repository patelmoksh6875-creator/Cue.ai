"""Overlap, loudness, brightness, sample rate and bass-swap checks on
SYNTHETIC audio (tones, noise, click tracks) -- no copyrighted material."""
import numpy as np
import pytest

import config
from mixing import align, assemble, levels, metrics, styles

SR = config.RENDER_SAMPLE_RATE
BPM = 120.0
L = 12


def tone(freq, seconds, amp=0.5):
    t = np.arange(int(SR * seconds)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def clip(freq_mid, freq_low, seconds=30, amp=0.3, bpm=BPM):
    """A mid tone + a low tone + kick-like clicks on the beat."""
    y = tone(freq_mid, seconds, amp) + tone(freq_low, seconds, amp)
    beat = 60.0 / bpm
    burst = np.hanning(int(0.03 * SR)).astype(np.float32) * 0.5
    for t in np.arange(0, seconds - 0.1, beat):
        i = int(t * SR)
        y[i : i + len(burst)] += burst
    return y


def render(y_a, y_b, trace=None, bpm=BPM, style="blend"):
    tl = assemble.plan_timeline(bpm, L)
    return assemble.assemble_mix(y_a, y_b, SR, tl, a_blend_start=10.0, b_blend_start=10.0, style=style, trace=trace) + (tl,)


def level_db(y, f, sr=SR):
    return metrics.band_db(y, sr, f - 15, f + 15)


# ---- timeline -----------------------------------------------------------------
def test_timeline_matches_spec_example():
    tl = assemble.plan_timeline(120, 12)
    assert (tl.n_beats, round(tl.lead_s, 2), round(tl.overlap_s, 2), round(tl.tail_s, 2)) == (16, 2.0, 8.0, 2.0)


@pytest.mark.parametrize("bpm", [60, 80, 100, 117.45, 128, 150, 174])
@pytest.mark.parametrize("length", [10, 12, 15])
def test_timeline_always_adds_up_and_has_an_overlap(bpm, length):
    tl = assemble.plan_timeline(bpm, length)
    assert tl.n_beats in config.MIX_OVERLAP_BEAT_OPTIONS
    assert tl.lead_s + tl.overlap_s + tl.tail_s == pytest.approx(length)
    assert tl.overlap_s > 0 and tl.lead_s > 0 and tl.tail_s > 0
    beats = tl.lead_s / (60 / bpm)
    assert beats == pytest.approx(round(beats))  # lead is a whole number of beats


def test_timeline_text_is_readable():
    assert assemble.plan_timeline(120, 12).text() == "0:00–0:02 song A · 0:02–0:10 both songs · 0:10–0:12 song B"


# ---- overlap exists, no gap, no sequential placement ------------------------------------
def test_both_songs_audible_in_overlap_middle_and_no_gap():
    a, b = clip(440, 60), clip(880, 80)
    full, report, tl = render(a, b)
    ov0, ov1 = int(tl.lead_s * SR), int((tl.lead_s + tl.overlap_s) * SR)
    mid = (ov0 + ov1) // 2
    middle = full[mid - SR // 2 : mid + SR // 2]
    a_solo = full[int(0.3 * SR) : int((tl.lead_s - 0.2) * SR)]
    b_solo = full[int((tl.lead_s + tl.overlap_s + 0.3) * SR) : int((L - 0.3) * SR)]
    assert level_db(middle, 440) > level_db(a_solo, 440) - 12   # A still present
    assert level_db(middle, 880) > level_db(b_solo, 880) - 12   # B already present
    # No gap: short-time level never drops >6 dB below the quieter solo section.
    hop = SR // 10
    rms = np.array([metrics.rms_dbfs(full[i : i + hop]) for i in range(0, len(full) - hop, hop)])
    floor = min(metrics.rms_dbfs(a_solo), metrics.rms_dbfs(b_solo)) - 6
    assert rms.min() > floor


def test_snippet_length_is_L_not_sum_of_clips():
    a, b = clip(440, 60), clip(880, 80)
    full, _, tl = render(a, b)
    assert len(full) / SR == pytest.approx(L, abs=60 / BPM)
    assert len(full) < len(a) + len(b)


def test_cut_style_has_no_overlap_by_design():
    # Guards the user-visible default: blend overlaps, cut does not.
    a, b = clip(440, 60), clip(880, 80)
    full, _, tl = render(a, b, style="cut")
    mid = int((tl.lead_s + tl.overlap_s / 2) * SR)
    seg_cut = full[mid + SR // 4 : mid + SR // 2]
    assert level_db(seg_cut, 440) < level_db(full[int(0.3 * SR):int(1.5 * SR)], 440) - 20


# ---- loudness, brightness, sample rate -------------------------------------------------
def test_loudness_is_matched_within_1db_even_if_b_is_much_quieter():
    a = clip(440, 60, amp=0.4)
    b = clip(880, 80, amp=0.4) * 0.07   # ~23 dB quieter, like a thin beat view
    stages = {}
    render(a, b, trace=lambda st, who, y, sr, ex: stages.setdefault((st, who), y))
    ra = metrics.rms_dbfs(stages[("4b after loudness match", "A")])
    rb = metrics.rms_dbfs(stages[("4b after loudness match", "B")])
    assert abs(ra - rb) <= 1.0


def test_both_songs_audible_in_overlap_when_b_is_quiet_before_matching():
    a = clip(440, 60, amp=0.4)
    b = clip(880, 80, amp=0.4) * 0.07
    full, _, tl = render(a, b)
    mid = int((tl.lead_s + tl.overlap_s / 2) * SR)
    middle = full[mid - SR // 2 : mid + SR // 2]
    b_solo = full[int((tl.lead_s + tl.overlap_s + 0.3) * SR) : int((L - 0.3) * SR)]
    assert level_db(middle, 880) > level_db(b_solo, 880) - 12


def test_stretch_preserves_level_and_brightness():
    rng = np.random.default_rng(1)
    noise = (rng.standard_normal(SR * 4) * 0.1).astype(np.float32)
    for ratio in (1.0, 1.03, 1.06, 1.3):
        out = align.time_stretch(noise, ratio, SR)
        assert len(out) == pytest.approx(len(noise) / ratio, rel=0.02)
        assert abs(metrics.rms_dbfs(out) - metrics.rms_dbfs(noise)) < 1.0
        before, after = metrics.hf_share(noise, SR), metrics.hf_share(out, SR)
        assert abs(10 * np.log10(after / before)) < 2.0   # within a couple of dB


def test_stretch_half_and_double_time():
    y = clip(440, 60, seconds=6)
    assert len(align.time_stretch(y, 2.0, SR)) == pytest.approx(len(y) / 2, rel=0.02)
    assert len(align.time_stretch(y, 0.5, SR)) == pytest.approx(len(y) * 2, rel=0.02)
    plan = align.plan_tempo_match(128, 64)       # exact half-time: no stretch needed
    assert plan.stretch_ratio == pytest.approx(1.0) and plan.used_half_double


def test_render_stages_use_common_sample_rate_and_mono():
    seen = []
    render(clip(440, 60), clip(880, 80), trace=lambda st, who, y, sr, ex: seen.append((sr, y.ndim)))
    assert seen and all(sr == config.RENDER_SAMPLE_RATE and nd == 1 for sr, nd in seen)


def test_peak_limited_to_ceiling():
    full, _, _ = render(clip(440, 60, amp=0.9), clip(880, 80, amp=0.9))
    assert metrics.peak_dbfs(full) == pytest.approx(config.MIX_PEAK_CEILING_DBFS, abs=0.2)


# ---- bass swap ---------------------------------------------------------------------------
def test_bass_gains_never_both_above_minus_6db():
    g = styles.blend_gains(10000)
    assert np.all(np.minimum(g["a_low"], g["b_low"]) <= 0.5 + 1e-9)
    assert g["a_low"][0] == 1.0 and g["b_low"][0] == 0.0       # A's bass at the start
    assert g["a_low"][-1] == 0.0 and g["b_low"][-1] == 1.0     # B's bass at the end
    # mids/highs are equal-power
    assert np.allclose(g["a_high"] ** 2 + g["b_high"] ** 2, 1.0)


def test_bass_swap_in_audio_low_bands_never_both_loud():
    n = SR * 8
    a, b = tone(60, 8, 0.5), tone(90, 8, 0.5)
    zeros = np.zeros(n, dtype=np.float32)
    a_share, b_share = styles.blend(a, zeros, SR), styles.blend(zeros, b, SR)
    ref_a, ref_b = metrics.rms_dbfs(a), metrics.rms_dbfs(b)
    hop = SR // 4
    for i in range(SR // 2, n - SR // 2, hop):  # skip filter edge effects
        da = metrics.rms_dbfs(a_share[i : i + hop]) - ref_a
        db = metrics.rms_dbfs(b_share[i : i + hop]) - ref_b
        assert min(da, db) <= -5.5   # never both above about -6 dB


def test_crossover_sums_back_to_the_input():
    y = clip(440, 60, seconds=3)
    low, high = styles.lr_split(y, SR, 150)
    assert np.max(np.abs(low + high - y)) < 0.02


def test_levels_helpers():
    a, b, info = levels.match_loudness(tone(440, 1, 0.5), tone(440, 1, 0.01), -18)
    assert abs(metrics.rms_dbfs(a) - metrics.rms_dbfs(b)) < 0.1
    assert metrics.peak_dbfs(levels.limit_peak(tone(440, 1, 0.1), -1)) == pytest.approx(-1, abs=0.05)
