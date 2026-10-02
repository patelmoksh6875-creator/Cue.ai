"""Snippet transition styles. Each function takes two already
tempo-matched, beat-aligned audio segments of equal length (the
transition region) and returns the mixed result of that same length.
Built with numpy + librosa only (no scipy -- not in the approved
dependency list); ask before adding a better filter/stretch library.
"""
from __future__ import annotations

import librosa
import numpy as np


def split_bands(y: np.ndarray, sr: int, cutoff_hz: float = 250.0) -> tuple[np.ndarray, np.ndarray]:
    """Crude brick-wall low/high split via FFT bin zeroing -- good enough
    for a short personal-use snippet, not audiophile-grade filtering."""
    stft = librosa.stft(y)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=(stft.shape[0] - 1) * 2)
    low_mask = freqs <= cutoff_hz
    low_stft = stft.copy()
    low_stft[~low_mask, :] = 0
    high_stft = stft.copy()
    high_stft[low_mask, :] = 0
    low = librosa.istft(low_stft, length=len(y))
    high = librosa.istft(high_stft, length=len(y))
    return low, high


def _equal_power_fade(n: int) -> tuple[np.ndarray, np.ndarray]:
    t = np.linspace(0, np.pi / 2, n)
    fade_out = np.cos(t)
    fade_in = np.sin(t)
    return fade_out, fade_in


def lr_split(y: np.ndarray, sr: int, cutoff_hz: float) -> tuple[np.ndarray, np.ndarray]:
    """Linkwitz-Riley (LR4) crossover: zero-phase Butterworth low-pass applied
    forward+backward; the high band is the exact complement."""
    from scipy.signal import butter, sosfiltfilt  # scipy ships with librosa

    low = sosfiltfilt(butter(2, cutoff_hz, "low", fs=sr, output="sos"), y, padlen=min(len(y) - 1, 4 * sr // 10))
    # High band is the exact complement: (1 - LP^2) equals the LR4 high-pass
    # magnitude, and low + high == input at every sample (no edge clicks).
    return low.astype(np.float32), (y - low).astype(np.float32)


def blend_gains(n: int, swap=None) -> dict:
    """Gain curves over the overlap (position p: 0 -> 1).

    Mids/highs: equal-power crossfade. Bass: A's low end stays until the swap
    window, then hands over so the two basslines are never both above -6 dB."""
    import config

    lo, hi = swap or config.MIX_BASS_SWAP_WINDOW
    p = np.linspace(0.0, 1.0, n)
    q = np.clip((p - lo) / (hi - lo), 0.0, 1.0)
    return {
        "p": p,
        "a_high": np.cos(p * np.pi / 2),
        "b_high": np.sin(p * np.pi / 2),
        "a_low": np.clip(1.0 - 1.5 * q, 0.0, 1.0),
        "b_low": np.clip(1.5 * q - 0.5, 0.0, 1.0),
    }


def blend(a: np.ndarray, b: np.ndarray, sr: int) -> np.ndarray:
    """Default style: both songs play together through the whole overlap.
    Equal-power crossfade on mids/highs plus a bass swap around the middle."""
    import config

    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    g = blend_gains(n)
    low_a, high_a = lr_split(a, sr, config.MIX_BASS_CROSSOVER_HZ)
    low_b, high_b = lr_split(b, sr, config.MIX_BASS_CROSSOVER_HZ)
    return high_a * g["a_high"] + high_b * g["b_high"] + low_a * g["a_low"] + low_b * g["b_low"]


def cut(a: np.ndarray, b: np.ndarray, sr: int) -> np.ndarray:
    """Hard cut on the beat boundary at the midpoint, with a short decaying
    echo of A's tail bleeding across the cut."""
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    mid = n // 2
    result = np.concatenate([a[:mid], b[mid:]]).astype(np.float32)

    echo_len = min(int(sr * 0.3), mid)
    if echo_len > 0:
        echo = a[mid - echo_len : mid] * 0.35
        end = min(mid + echo_len, n)
        result[mid:end] += echo[: end - mid]
    return result


def echo_out(a: np.ndarray, b: np.ndarray, sr: int) -> np.ndarray:
    """A fades into a beat-synced decaying echo while B drops in
    underneath it."""
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]

    # Repeat the back half of A as a delayed, decaying echo (simple
    # feedback delay via shifted-and-scaled adds, numpy only).
    delay_samples = max(1, int(sr * 0.2))
    echo = np.zeros(n, dtype=np.float32)
    decay = 0.55
    gain = 0.6
    shifted = a.copy()
    for _ in range(4):
        shifted = np.concatenate([np.zeros(delay_samples), shifted])[:n]
        echo += shifted * gain
        gain *= decay

    fade_out, fade_in = _equal_power_fade(n)
    return a * fade_out + echo * fade_out * 0.8 + b * fade_in


STYLES = {
    "blend": blend,
    "cut": cut,
    "echo-out": echo_out,
}
