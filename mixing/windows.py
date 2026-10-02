"""Pick WHERE inside the two ~30s previews to blend.

Slides candidate windows across both clips and scores each pair on groove
compatibility: drum-pattern (low-frequency onset) similarity at the best
lag, energy match, tempo stability inside each window, and onset density.
Returns the top few DISTINCT pairs.

HONEST LIMIT: this only chooses among the audio that is already in the two
clips. It cannot reach a section of the song that the 30s preview doesn't
contain -- if the clip missed the part that matches, every candidate here
is the wrong part too.
"""
from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np

from mixing import align

HOP = 512


@dataclass
class WindowCandidate:
    a_blend_start: float   # seconds into clip A where the blend begins
    b_blend_start: float   # seconds into (tempo-matched) clip B where the blend begins
    score: float
    drum_corr: float       # kick-pattern correlation at the best lag (0..1)
    energy_match: float
    stability: float
    density_match: float


def beat_interval_cv(beats: np.ndarray, start: float, end: float) -> float | None:
    """Coefficient of variation of beat spacing inside [start, end]; None if too few beats."""
    inside = beats[(beats >= start) & (beats <= end)]
    if len(inside) < 4:
        return None
    iv = np.diff(inside)
    return float(iv.std() / iv.mean())


def _stability(cv: float | None) -> float:
    return 0.4 if cv is None else float(1.0 - np.clip(cv / 0.15, 0.0, 1.0))


def _snap(t: float, beats: np.ndarray, max_dist: float) -> float:
    if len(beats) == 0:
        return t
    nearest = beats[np.argmin(np.abs(beats - t))]
    return float(nearest) if abs(nearest - t) <= max_dist else t


def _norm(seg: np.ndarray) -> np.ndarray:
    seg = seg - seg.mean()
    n = np.linalg.norm(seg)
    return seg / n if n > 1e-9 else seg


def _best_lag(env_a: np.ndarray, env_b: np.ndarray, fa: int, fb: int, n: int, max_lag: int) -> tuple[float, int]:
    """Best normalized correlation of A's window vs B's window shifted by lag frames."""
    seg_a = _norm(env_a[fa : fa + n])
    best, best_lag = -1.0, 0
    for lag in range(-max_lag, max_lag + 1):
        start = fb + lag
        if start < 0 or start + n > len(env_b):
            continue
        c = float(np.dot(seg_a, _norm(env_b[start : start + n])))
        if c > best:
            best, best_lag = c, lag
    return max(best, 0.0), best_lag


def rank_windows(
    y_a: np.ndarray, y_b: np.ndarray, sr: int,
    beats_a: np.ndarray, beats_b: np.ndarray,
    blend_s: float, lead_s: float, tail_s: float,
    bpm: float, top: int = 3, step_s: float = 1.0,
) -> list[WindowCandidate]:
    """y_b must already be tempo-matched to y_a. Returns best-first candidates."""
    fps = sr / HOP
    env_a = align._low_freq_envelope(y_a, sr)
    env_b = align._low_freq_envelope(y_b, sr)
    rms_a = librosa.feature.rms(y=y_a, hop_length=HOP)[0]
    rms_b = librosa.feature.rms(y=y_b, hop_length=HOP)[0]
    onsets_a = librosa.onset.onset_strength(y=y_a, sr=sr, hop_length=HOP)
    onsets_b = librosa.onset.onset_strength(y=y_b, sr=sr, hop_length=HOP)
    n = int(blend_s * fps)
    beat_s = 60.0 / bpm
    max_lag = max(2, int(0.5 * beat_s * fps))
    dur_a, dur_b = len(y_a) / sr, len(y_b) / sr

    a_starts = np.arange(lead_s, dur_a - blend_s + 1e-6, step_s)
    b_starts = np.arange(0.0, dur_b - blend_s - tail_s + 1e-6, step_s)
    if len(a_starts) == 0 or len(b_starts) == 0:
        return []
    a_starts = sorted({round(_snap(float(t), beats_a, beat_s / 2), 3) for t in a_starts})
    b_starts = sorted({round(_snap(float(t), beats_b, beat_s / 2), 3) for t in b_starts})

    def feats(start, env, rms, ons, beats):
        f0 = int(start * fps)
        r = float(rms[f0 : f0 + n].mean()) if len(rms) > f0 else 0.0
        d = float(ons[f0 : f0 + n].mean()) if len(ons) > f0 else 0.0
        return f0, r, d, _stability(beat_interval_cv(beats, start, start + blend_s))

    fa = {t: feats(t, env_a, rms_a, onsets_a, beats_a) for t in a_starts}
    fb = {t: feats(t, env_b, rms_b, onsets_b, beats_b) for t in b_starts}

    scored: list[WindowCandidate] = []
    for ta, (f0a, ra, da, sa) in fa.items():
        for tb, (f0b, rb, db, sb) in fb.items():
            corr, lag = _best_lag(env_a, env_b, f0a, f0b, n, max_lag)
            energy = 1.0 - abs(ra - rb) / max(ra, rb, 1e-6)
            density = min(da, db) / max(da, db, 1e-6)
            stab = (sa + sb) / 2
            score = 0.45 * corr + 0.25 * energy + 0.20 * stab + 0.10 * density
            scored.append(WindowCandidate(
                a_blend_start=ta,
                b_blend_start=max(0.0, tb + lag / fps),  # fold the best lag into B's start
                score=round(score, 4), drum_corr=round(corr, 4),
                energy_match=round(energy, 4), stability=round(stab, 4), density_match=round(density, 4),
            ))
    scored.sort(key=lambda c: c.score, reverse=True)

    picked: list[WindowCandidate] = []
    for c in scored:
        if all(abs(c.a_blend_start - p.a_blend_start) >= 2.5 or abs(c.b_blend_start - p.b_blend_start) >= 2.5
               for p in picked):
            picked.append(c)
        if len(picked) == top:
            break
    return picked
