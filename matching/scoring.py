"""Pure scoring functions: no I/O, no database, no network. Every function
here takes plain data and returns a plain score so it can be unit-tested in
isolation and reused anywhere (CLI, Streamlit, tests) without a DB or API.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import config


def bpm_score(
    seed_bpm: Optional[float],
    candidate_bpm: Optional[float],
    tolerance_pct: float = config.BPM_TOLERANCE_PCT,
    half_double_matching: bool = config.BPM_HALF_DOUBLE_MATCHING,
) -> Optional[float]:
    """1.0 for an exact match, decaying smoothly to 0 past `tolerance_pct`.
    Also checks half-time/double-time relationships when enabled and picks
    whichever ratio scores best. Returns None if either BPM is missing."""
    if not seed_bpm or not candidate_bpm or seed_bpm <= 0 or candidate_bpm <= 0:
        return None

    candidates = [candidate_bpm]
    if half_double_matching:
        candidates += [candidate_bpm * 2, candidate_bpm / 2]

    best = 0.0
    for c in candidates:
        pct_diff = abs(c - seed_bpm) / seed_bpm
        # Linear decay: 1.0 at 0% diff, 0.0 at 2x tolerance, floored at 0.
        score = max(0.0, 1.0 - pct_diff / (tolerance_pct * 2))
        best = max(best, score)
    return round(best, 4)


def _parse_camelot(code: str) -> Optional[tuple[int, str]]:
    code = code.strip().upper()
    if len(code) < 2 or code[-1] not in ("A", "B"):
        return None
    try:
        number = int(code[:-1])
    except ValueError:
        return None
    if not (1 <= number <= 12):
        return None
    return number, code[-1]


def camelot_distance(a: str, b: str) -> Optional[int]:
    """Steps apart on the Camelot wheel. 0 = identical, 1 = adjacent number
    (same letter) or same number (relative major/minor). Returns None if
    either code is unparseable."""
    pa, pb = _parse_camelot(a), _parse_camelot(b)
    if pa is None or pb is None:
        return None
    na, la = pa
    nb, lb = pb
    if na == nb and la == lb:
        return 0
    num_diff = min(abs(na - nb), 12 - abs(na - nb))
    if la == lb:
        return num_diff
    if na == nb:
        return 1
    return num_diff + 1


def key_score(seed_camelot: Optional[str], candidate_camelot: Optional[str]) -> Optional[float]:
    """Soft Camelot-wheel compatibility score. Returns None if either key
    is missing/unparseable, since librosa key detection is unreliable and
    this should not silently zero out a candidate's total score."""
    if not seed_camelot or not candidate_camelot:
        return None
    distance = camelot_distance(seed_camelot, candidate_camelot)
    if distance is None:
        return None
    return config.CAMELOT_COMPATIBILITY_BY_DISTANCE.get(
        distance, config.CAMELOT_DEFAULT_SCORE
    )


def tags_score(seed_tags: set[str], candidate_tags: set[str]) -> Optional[float]:
    """Jaccard overlap of tag sets. Returns None (not 0) when either side
    has no tags at all, so callers can fall back to genre-only scoring
    instead of unfairly zeroing out obscure tracks."""
    if not seed_tags or not candidate_tags:
        return None
    seed_norm = {t.strip().lower() for t in seed_tags}
    cand_norm = {t.strip().lower() for t in candidate_tags}
    intersection = seed_norm & cand_norm
    union = seed_norm | cand_norm
    if not union:
        return None
    return round(len(intersection) / len(union), 4)


def genre_score(seed_genre: Optional[str], candidate_genre: Optional[str]) -> Optional[float]:
    """Exact (case-insensitive) genre match. Deezer genre is coarse
    album-level data, so this is necessarily a blunt signal."""
    if not seed_genre or not candidate_genre:
        return None
    return 1.0 if seed_genre.strip().lower() == candidate_genre.strip().lower() else 0.0


def energy_score(seed_energy: Optional[float], candidate_energy: Optional[float]) -> Optional[float]:
    """1.0 for identical energy, decaying linearly with absolute difference
    (energy is normalized to 0..1 by analysis/audio.py)."""
    if seed_energy is None or candidate_energy is None:
        return None
    return round(max(0.0, 1.0 - abs(seed_energy - candidate_energy)), 4)


@dataclass
class ScoreBreakdown:
    bpm: Optional[float]
    key: Optional[float]
    tags: Optional[float]
    genre: Optional[float]
    energy: Optional[float]
    total: float
    label: str


def total_score(
    bpm: Optional[float],
    key: Optional[float],
    tags: Optional[float],
    genre: Optional[float],
    energy: Optional[float],
    weights: Optional[dict[str, float]] = None,
) -> ScoreBreakdown:
    """Weighted sum over whatever components are available. Missing
    components (None) are excluded and the remaining weights are
    renormalized to sum to 1, so a track missing tags isn't punished twice
    for something no adapter could supply."""
    weights = weights or config.SCORE_WEIGHTS
    components = {"bpm": bpm, "key": key, "tags": tags, "genre": genre, "energy": energy}
    available = {k: v for k, v in components.items() if v is not None}

    if not available:
        total = 0.0
    else:
        weight_sum = sum(weights[k] for k in available)
        if weight_sum <= 0:
            total = 0.0
        else:
            total = sum(weights[k] * v for k, v in available.items()) / weight_sum

    total = round(total, 4)
    label = "safe" if _is_safe(bpm, key) else "adventurous"
    return ScoreBreakdown(bpm=bpm, key=key, tags=tags, genre=genre, energy=energy, total=total, label=label)


def _is_safe(bpm: Optional[float], key: Optional[float]) -> bool:
    if bpm is None or key is None:
        return False
    return bpm >= config.SAFE_BPM_SCORE_MIN and key >= config.SAFE_KEY_SCORE_MIN


def percent_match(total_score_value: float) -> int:
    """A 0..1 total_score as a whole-number percent for display, e.g.
    "87% match". This is a relative score from the weighted factors, not
    a probability the mix will sound good -- never label it "accuracy" or
    "chance" in the UI."""
    return round(max(0.0, min(1.0, total_score_value)) * 100)


def bpm_relation(seed_bpm: Optional[float], candidate_bpm: Optional[float]) -> Optional[str]:
    """Display-only: how a candidate's BPM relates to the seed's, so the
    UI can show e.g. "70 BPM (half-time of 140)". Independent of
    bpm_score()'s actual scoring math -- this never affects ranking."""
    if not seed_bpm or not candidate_bpm or seed_bpm <= 0 or candidate_bpm <= 0:
        return None
    tolerance = config.BPM_TOLERANCE_PCT
    if abs(candidate_bpm - seed_bpm) / seed_bpm <= tolerance:
        return "exact"
    if abs(candidate_bpm * 2 - seed_bpm) / seed_bpm <= tolerance:
        return "half-time"
    if abs(candidate_bpm / 2 - seed_bpm) / seed_bpm <= tolerance:
        return "double-time"
    return None
