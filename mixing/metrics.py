"""Pure audio metrics used by the render debug path and tests."""
from __future__ import annotations

import numpy as np

HF_CUTOFF_HZ = 4000.0


def rms_dbfs(y: np.ndarray) -> float:
    r = float(np.sqrt(np.mean(np.square(y)))) if len(y) else 0.0
    return -120.0 if r < 1e-9 else 20 * np.log10(r)


def peak_dbfs(y: np.ndarray) -> float:
    p = float(np.max(np.abs(y))) if len(y) else 0.0
    return -120.0 if p < 1e-9 else 20 * np.log10(p)


def spectral_centroid_hz(y: np.ndarray, sr: int) -> float:
    if len(y) == 0:
        return 0.0
    mag = np.abs(np.fft.rfft(y))
    freqs = np.fft.rfftfreq(len(y), 1 / sr)
    return float((freqs * mag).sum() / max(mag.sum(), 1e-12))


def hf_share(y: np.ndarray, sr: int, cutoff: float = HF_CUTOFF_HZ) -> float:
    """Share (0..1) of spectral energy above `cutoff` Hz."""
    if len(y) == 0:
        return 0.0
    power = np.abs(np.fft.rfft(y)) ** 2
    freqs = np.fft.rfftfreq(len(y), 1 / sr)
    return float(power[freqs >= cutoff].sum() / max(power.sum(), 1e-12))


def band_db(y: np.ndarray, sr: int, lo: float, hi: float) -> float:
    """Energy (dB, relative to full scale sine-ish) of a band; for tests."""
    if len(y) == 0:
        return -120.0
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y)))) / (len(y) / 4)
    freqs = np.fft.rfftfreq(len(y), 1 / sr)
    peak = float(spec[(freqs >= lo) & (freqs <= hi)].max()) if np.any((freqs >= lo) & (freqs <= hi)) else 0.0
    return -120.0 if peak < 1e-9 else 20 * np.log10(peak)


def describe(y: np.ndarray, sr: int, channels: int = 1) -> dict:
    return {
        "sr": sr, "channels": channels, "duration_s": round(len(y) / sr, 2),
        "rms_dbfs": round(rms_dbfs(y), 1), "peak_dbfs": round(peak_dbfs(y), 1),
        "centroid_hz": round(spectral_centroid_hz(y, sr)), "hf_share": round(hf_share(y, sr), 3),
    }
