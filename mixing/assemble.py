"""Build the final snippet from two tempo-matched, aligned clips.

Required timeline (config.py): for length L and beat period T = 60/BPM,
  1. A alone for >= MIX_MIN_SOLO_S (a whole number of beats),
  2. BOTH songs together for N beats -- the largest of MIX_OVERLAP_BEAT_OPTIONS
     {16, 8, 4} that leaves >= MIX_MIN_SOLO_S of A before and of B after,
  3. B alone for the remainder.
Total duration is exactly L (never len(A) + len(B)).
Inputs are loudness-matched first; the sum is peak-limited to about -1 dBFS.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

import config
from mixing import levels
from mixing.styles import STYLES


@dataclass
class Timeline:
    bpm: float
    length_s: float
    lead_s: float
    overlap_s: float
    tail_s: float
    n_beats: int

    def segments(self) -> list[dict]:
        return [
            {"label": "song A", "start": 0.0, "end": round(self.lead_s, 2)},
            {"label": "both songs", "start": round(self.lead_s, 2), "end": round(self.lead_s + self.overlap_s, 2)},
            {"label": "song B", "start": round(self.lead_s + self.overlap_s, 2), "end": round(self.length_s, 2)},
        ]

    def text(self) -> str:
        def mmss(t: float) -> str:
            return f"{int(t // 60)}:{int(round(t) % 60):02d}"
        return " · ".join(f"{mmss(s['start'])}–{mmss(s['end'])} {s['label']}" for s in self.segments())


def plan_timeline(bpm: float, length_s: float) -> Timeline:
    T = 60.0 / bpm
    lead = math.ceil(config.MIX_MIN_SOLO_S / T - 1e-9) * T
    for n in config.MIX_OVERLAP_BEAT_OPTIONS:
        overlap = n * T
        tail = length_s - lead - overlap
        if tail >= config.MIX_MIN_SOLO_S - 0.15 * T:
            return Timeline(bpm, length_s, lead, overlap, tail, n)
    n = config.MIX_OVERLAP_BEAT_OPTIONS[-1]  # very slow tempo: smallest overlap, shortest solos
    overlap = n * T
    lead = min(lead, max(T, (length_s - overlap) / 2))
    return Timeline(bpm, length_s, lead, overlap, max(length_s - lead - overlap, T), n)


def take(y: np.ndarray, sr: int, start_s: float, length_s: float) -> np.ndarray:
    start = max(0, int(round(start_s * sr)))
    n = int(round(length_s * sr))
    seg = y[start : start + n]
    return np.pad(seg, (0, n - len(seg))) if len(seg) < n else seg


def assemble_mix(
    y_a: np.ndarray, y_b: np.ndarray, sr: int, tl: Timeline,
    a_blend_start: float, b_blend_start: float, style: str = "blend", trace=None,
) -> tuple[np.ndarray, dict]:
    """y_a / y_b: full clips at `sr`, y_b already tempo-matched to A.
    a_blend_start / b_blend_start: where (seconds) the overlap begins in each."""
    tr = trace or (lambda *a, **k: None)
    a_region = take(y_a, sr, a_blend_start - tl.lead_s, tl.lead_s + tl.overlap_s)
    b_region = take(y_b, sr, b_blend_start, tl.overlap_s + tl.tail_s)
    tr("4 after alignment/trim", "A", a_region, sr, {})
    tr("4 after alignment/trim", "B", b_region, sr, {})

    a_region, b_region, loud = levels.match_loudness(a_region, b_region, config.MIX_TARGET_RMS_DBFS)
    tr("4b after loudness match", "A", a_region, sr, loud)
    tr("4b after loudness match", "B", b_region, sr, loud)

    n_lead, n_over = int(round(tl.lead_s * sr)), int(round(tl.overlap_s * sr))
    a_lead, a_over = a_region[:n_lead], a_region[n_lead : n_lead + n_over]
    b_over, b_tail = b_region[:n_over], b_region[n_over:]

    style_fn = STYLES[style]
    zeros = np.zeros_like(a_over)
    tr("5 after filters/EQ/gain (this song's share of the overlap)", "A", style_fn(a_over, zeros, sr), sr, {})
    tr("5 after filters/EQ/gain (this song's share of the overlap)", "B", style_fn(zeros, b_over, sr), sr, {})
    overlap = style_fn(a_over, b_over, sr)

    full = np.concatenate([a_lead, overlap, b_tail]).astype(np.float32)
    full = levels.limit_peak(full, config.MIX_PEAK_CEILING_DBFS)
    tr("7 final mix", "mix", full, sr, {"timeline": tl.text(), "overlap_beats": tl.n_beats})
    return full, {"loudness": loud, "timeline": tl.segments(), "timeline_text": tl.text()}
