"""librosa-based audio analysis: BPM verification, key/Camelot, energy.

Deezer's own BPM field is frequently missing or wrong by a factor of two
(half/double time), so every candidate that survives the hard filter gets
its 30s preview analyzed here for a verified value. librosa's key
detection is mediocre, which is why key is a *soft* score elsewhere, not
a hard filter.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
import librosa
import numpy as np

import config

# Camelot wheel: maps (pitch class, mode) -> Camelot code.
# Mode 0 = minor (A), mode 1 = major (B) in librosa/essentia key-detection convention.
_CAMELOT_MAJOR = {
    0: "8B", 1: "3B", 2: "10B", 3: "5B", 4: "12B", 5: "7B",
    6: "2B", 7: "9B", 8: "4B", 9: "11B", 10: "6B", 11: "1B",
}
_CAMELOT_MINOR = {
    0: "5A", 1: "12A", 2: "7A", 3: "2A", 4: "9A", 5: "4A",
    6: "11A", 7: "6A", 8: "1A", 9: "8A", 10: "3A", 11: "10A",
}
_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

_KRUMHANSL_MAJOR = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
_KRUMHANSL_MINOR = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)


@dataclass
class AnalysisResult:
    bpm: float
    bpm_confidence: float
    key: str  # e.g. "C major", "A minor"
    camelot: str
    energy: float
    bpm_disagreement: Optional[str] = None  # e.g. "half", "double", None


def download_preview(preview_url: str) -> Path:
    resp = httpx.get(preview_url, timeout=15.0, follow_redirects=True)
    resp.raise_for_status()
    suffix = Path(preview_url.split("?")[0]).suffix or ".mp3"  # iTunes previews are .m4a
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(resp.content)
    tmp.close()
    return Path(tmp.name)


def _estimate_key(chroma_mean: np.ndarray) -> tuple[str, str]:
    """Krumhansl-Schmuckler key-profile correlation. Returns (label, camelot)."""
    best_score = -np.inf
    best_pitch = 0
    best_mode = "major"
    for shift in range(12):
        major_profile = np.roll(_KRUMHANSL_MAJOR, shift)
        minor_profile = np.roll(_KRUMHANSL_MINOR, shift)
        major_score = np.corrcoef(chroma_mean, major_profile)[0, 1]
        minor_score = np.corrcoef(chroma_mean, minor_profile)[0, 1]
        if major_score > best_score:
            best_score, best_pitch, best_mode = major_score, shift, "major"
        if minor_score > best_score:
            best_score, best_pitch, best_mode = minor_score, shift, "minor"
    label = f"{_PITCH_CLASSES[best_pitch]} {best_mode}"
    camelot = (_CAMELOT_MAJOR if best_mode == "major" else _CAMELOT_MINOR)[best_pitch]
    return label, camelot


def analyze_samples(
    y: np.ndarray, sr: int, deezer_bpm: Optional[float] = None
) -> AnalysisResult:
    """BPM/key/energy on already-decoded audio -- used for the full-mix
    preview, an official instrumental, or the drums+low-end beat view."""
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])

    # Onset-strength-based confidence proxy: how peaky/regular the beat is.
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    bpm_confidence = float(
        np.clip(np.std(onset_env) / (np.mean(onset_env) + 1e-6) / 3.0, 0.0, 1.0)
    )

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    key_label, camelot = _estimate_key(chroma.mean(axis=1))

    rms = librosa.feature.rms(y=y)[0]
    # Empirically, mastered previews sit around rms 0.05-0.3; scale so
    # that range maps to roughly 0.2-1.0 rather than saturating at 1.
    energy = float(np.clip(np.mean(rms) * 4, 0.0, 1.0))

    return AnalysisResult(
        bpm=bpm,
        bpm_confidence=bpm_confidence,
        key=key_label,
        camelot=camelot,
        energy=energy,
        bpm_disagreement=_bpm_disagreement(bpm, deezer_bpm),
    )


def analyze_preview(preview_url: str, deezer_bpm: Optional[float] = None) -> AnalysisResult:
    """Download a preview, decode it, and analyze it. Cleans up the temp
    file when done, even on error."""
    tmp_path = download_preview(preview_url)
    try:
        y, sr = librosa.load(str(tmp_path), sr=config.PREVIEW_SAMPLE_RATE, mono=True)
        return analyze_samples(y, sr, deezer_bpm)
    finally:
        tmp_path.unlink(missing_ok=True)


def _bpm_disagreement(verified_bpm: float, deezer_bpm: Optional[float]) -> Optional[str]:
    if not deezer_bpm or deezer_bpm <= 0:
        return None
    ratio = verified_bpm / deezer_bpm
    if 0.47 <= ratio <= 0.53:
        return "half"
    if 1.9 <= ratio <= 2.1:
        return "double"
    if abs(ratio - 1.0) > 0.1:
        return "mismatch"
    return None
