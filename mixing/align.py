"""Tempo matching and beat alignment for the mix snippet maker.

Hard constraint this whole module works around: the only audio available
is Deezer's 30-second preview clips, not full tracks, so alignment can
only ever be approximate (see CLAUDE_HANDOFF_V2_WEB_UI.md Section 6).
librosa gives beats, not bars/downbeats, so within-bar offset is picked
by maximizing low-frequency (kick) onset overlap rather than assumed.
"""
from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np

# A stretch beyond this quality-degrades noticeably (librosa's phase
# vocoder time_stretch gets smeary past this point on real songs).
MAX_CLEAN_STRETCH_PCT = 0.08


@dataclass
class TempoMatch:
    stretch_ratio: float  # >1.0 = sped up, <1.0 = slowed down
    stretch_pct: float  # abs(ratio - 1.0)
    exceeds_quality_threshold: bool
    used_half_double: bool


def plan_tempo_match(seed_bpm: float, candidate_bpm: float) -> TempoMatch:
    """Decide how much to time-stretch the candidate to match the seed's
    BPM, picking whichever of [1x, 2x, 0.5x] the candidate's tempo gives
    the smallest stretch (half/double-time aware, same idea as
    matching/scoring.bpm_relation but for rendering, not scoring)."""
    options = [candidate_bpm, candidate_bpm * 2, candidate_bpm / 2]
    ratios = [seed_bpm / c for c in options if c > 0]
    best_ratio = min(ratios, key=lambda r: abs(r - 1.0))
    used_half_double = best_ratio != ratios[0]
    stretch_pct = abs(best_ratio - 1.0)
    return TempoMatch(
        stretch_ratio=best_ratio,
        stretch_pct=stretch_pct,
        exceeds_quality_threshold=stretch_pct > MAX_CLEAN_STRETCH_PCT,
        used_half_double=used_half_double,
    )


def time_stretch(y: np.ndarray, ratio: float) -> np.ndarray:
    """Stretch audio so its tempo multiplies by `ratio` (>1 = faster)."""
    if abs(ratio - 1.0) < 1e-3:
        return y
    return librosa.effects.time_stretch(y, rate=ratio)


def _low_freq_envelope(y: np.ndarray, sr: int, cutoff_hz: float = 150.0) -> np.ndarray:
    """Onset-strength envelope restricted to low frequencies (kick drum
    range), used to judge beat alignment by feel rather than assumption."""
    stft = librosa.stft(y)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=(stft.shape[0] - 1) * 2)
    low_mask = freqs <= cutoff_hz
    low_stft = stft.copy()
    low_stft[~low_mask, :] = 0
    low_audio = librosa.istft(low_stft, length=len(y))
    return librosa.onset.onset_strength(y=low_audio, sr=sr)


def best_beat_offset(a: np.ndarray, b: np.ndarray, sr: int, beat_times_b: np.ndarray) -> float:
    """Among B's first few beats, pick the start offset (in seconds) that
    best aligns B's kick-drum onsets with A's, within roughly one bar
    (~4 beats). Returns 0.0 if there aren't enough beats to compare."""
    candidates = beat_times_b[:4] if len(beat_times_b) >= 1 else np.array([0.0])
    env_a = _low_freq_envelope(a, sr)
    best_offset = 0.0
    best_score = -np.inf
    for offset_s in candidates:
        offset_samples = int(offset_s * sr)
        shifted = b[offset_samples:]
        if len(shifted) < sr:  # not enough audio left to compare meaningfully
            continue
        env_b = _low_freq_envelope(shifted, sr)
        n = min(len(env_a), len(env_b))
        if n < 4:
            continue
        score = float(np.corrcoef(env_a[:n], env_b[:n])[0, 1])
        if score > best_score:
            best_score, best_offset = score, offset_s
    return best_offset
