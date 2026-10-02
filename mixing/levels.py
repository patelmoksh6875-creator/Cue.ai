"""Loudness matching and peak limiting (numpy only)."""
from __future__ import annotations

import numpy as np

from mixing.metrics import rms_dbfs

MAX_GAIN_DB = 30.0


def apply_gain_db(y: np.ndarray, db: float) -> np.ndarray:
    return (y * (10 ** (db / 20))).astype(np.float32)


def match_loudness(a: np.ndarray, b: np.ndarray, target_db: float) -> tuple[np.ndarray, np.ndarray, dict]:
    """Scale both clips to the same RMS (target_db). Silent clips are left alone."""
    out, gains = [], []
    before = (rms_dbfs(a), rms_dbfs(b))
    for y, rms in zip((a, b), before):
        g = 0.0 if rms < -90 else float(np.clip(target_db - rms, -MAX_GAIN_DB, MAX_GAIN_DB))
        gains.append(g)
        out.append(apply_gain_db(y, g))
    return out[0], out[1], {
        "rms_before_db": [round(x, 1) for x in before],
        "gain_db": [round(g, 1) for g in gains],
        "rms_after_db": [round(rms_dbfs(out[0]), 1), round(rms_dbfs(out[1]), 1)],
    }


def limit_peak(y: np.ndarray, ceiling_db: float) -> np.ndarray:
    """Scale so the peak sits at ceiling_db (down if too hot, up if too quiet)."""
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak < 1e-9:
        return y.astype(np.float32)
    return (y * (10 ** (ceiling_db / 20) / peak)).astype(np.float32)
