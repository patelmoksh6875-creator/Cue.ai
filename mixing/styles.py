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


def blend(a: np.ndarray, b: np.ndarray, sr: int) -> np.ndarray:
    """Default style: beat-matched equal-power crossfade with an EQ bass
    swap -- A's low end cuts out faster as B's comes in, the standard DJ
    transition, instead of both basslines clashing throughout the blend."""
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    fade_out, fade_in = _equal_power_fade(n)

    low_a, high_a = split_bands(a, sr)
    low_b, high_b = split_bands(b, sr)

    # Bass swaps over the first 60% of the blend (faster than the overall
    # fade) so the low end doesn't clash for the whole transition.
    bass_n = max(1, int(n * 0.6))
    bass_fade_out, bass_fade_in = _equal_power_fade(bass_n)
    low_fade_out = np.concatenate([bass_fade_out, np.zeros(n - bass_n)])
    low_fade_in = np.concatenate([bass_fade_in, np.ones(n - bass_n)])

    low_mix = low_a * low_fade_out + low_b * low_fade_in
    high_mix = high_a * fade_out + high_b * fade_in
    return low_mix + high_mix


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
