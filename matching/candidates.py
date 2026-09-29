"""Candidate discovery: gather a broad pool from Last.fm similar tracks,
Deezer related-artist top tracks, and Deezer genre charts; resolve
everything to Deezer track IDs; dedupe; and apply the cheap BPM hard
filter before any expensive librosa analysis happens.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

import config
from analysis import audio
from db import repo
from matching import scoring
from sources import deezer
from sources.lastfm import LastFMError, LastFMNotConfigured, get_similar_tracks, get_top_tags

_FEATURE_PATTERN = re.compile(r"\(feat\.?[^)]*\)|\bfeat\.?[^-]*$", re.IGNORECASE)
_VERSION_PATTERN = re.compile(
    r"\((remix|live|radio edit|acoustic|extended|remaster(ed)?|mono|stereo)[^)]*\)",
    re.IGNORECASE,
)

# A fuzzy match below this similarity is not trusted as "the same track".
RESOLVE_MATCH_THRESHOLD = 0.6


def normalize_title(title: str) -> str:
    """Strip feature credits, remix/live/edit tags, and punctuation so
    duplicate versions of the same song collapse to one key."""
    t = _FEATURE_PATTERN.sub("", title)
    t = _VERSION_PATTERN.sub("", t)
    t = re.sub(r"[^a-z0-9 ]", "", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def resolve_to_deezer(artist: str, title: str) -> deezer.DeezerTrack | None:
    """Fuzzy-resolve a (artist, title) pair -- as Last.fm returns it -- to
    the best-matching Deezer track. Handles punctuation and minor spelling
    differences via difflib; returns None if nothing matches well enough."""
    query = f"{artist} {title}"
    results = deezer.search_tracks(query, limit=5)
    if not results:
        return None

    target = normalize_title(f"{artist} {title}")
    best_track = None
    best_score = 0.0
    for candidate in results:
        candidate_key = normalize_title(f"{candidate.artist_name} {candidate.title}")
        score = _similarity(target, candidate_key)
        if score > best_score:
            best_score, best_track = score, candidate

    if best_track is None or best_score < RESOLVE_MATCH_THRESHOLD:
        return None
    return best_track


@dataclass
class Candidate:
    track: deezer.DeezerTrack
    dedupe_key: str


def _dedupe_key(track: deezer.DeezerTrack) -> str:
    if track.isrc:
        return f"isrc:{track.isrc}"
    return f"title:{normalize_title(track.title)}:{track.artist_id}"


def _dedupe(tracks: list[deezer.DeezerTrack]) -> list[deezer.DeezerTrack]:
    seen: dict[str, deezer.DeezerTrack] = {}
    for t in tracks:
        key = _dedupe_key(t)
        if key not in seen:
            seen[key] = t
    return list(seen.values())


def gather_candidate_pool(seed: deezer.DeezerTrack) -> list[deezer.DeezerTrack]:
    """Assemble a raw, deduped candidate pool from all configured sources.
    Aims for config.CANDIDATE_POOL_TARGET_MIN..MAX before hard filtering."""
    pool: list[deezer.DeezerTrack] = []

    try:
        similar = get_similar_tracks(seed.artist_name, seed.title, limit=40)
        for s in similar:
            resolved = resolve_to_deezer(s.artist, s.title)
            if resolved:
                pool.append(resolved)
    except LastFMNotConfigured:
        pass  # No Last.fm key: fall back to Deezer-only discovery below.

    pool.extend(deezer.get_artist_related(seed.artist_id, limit=60))
    pool.extend(deezer.get_chart_tracks(genre_id=0, limit=50))

    pool = [t for t in pool if t.id != seed.id]
    return _dedupe(pool)


def hard_filter_bpm(
    seed_bpm: float | None,
    candidates: list[deezer.DeezerTrack],
    tolerance_pct: float = config.BPM_TOLERANCE_PCT,
) -> list[deezer.DeezerTrack]:
    """Cheap pre-filter using Deezer's own (often-missing) BPM field, so
    librosa only has to analyze tracks that already look plausible. A
    candidate with no Deezer BPM is kept -- it needs analysis to know
    either way, not rejection for missing data."""
    if not seed_bpm:
        return candidates
    kept = []
    for c in candidates:
        if c.bpm is None:
            kept.append(c)
            continue
        score = scoring.bpm_score(seed_bpm, c.bpm, tolerance_pct=tolerance_pct)
        if score is not None and score > 0.0:
            kept.append(c)
    return kept


def _get_tags(track: deezer.DeezerTrack) -> set[str]:
    try:
        return {name for name, _weight in get_top_tags(track.artist_name, track.title)}
    except (LastFMNotConfigured, LastFMError):
        return set()


def _analyze_candidate(track: deezer.DeezerTrack) -> audio.AnalysisResult | None:
    """Lazy, cached librosa analysis: skip tracks already analyzed at the
    current analyzer version, skip tracks with no preview available."""
    cached = repo.get_audio_features(track.id)
    if cached is not None and cached.analyzer_version == config.ANALYZER_VERSION:
        return audio.AnalysisResult(
            bpm=cached.bpm_verified,
            bpm_confidence=cached.bpm_confidence,
            key=cached.key,
            camelot=cached.camelot,
            energy=cached.energy,
        )
    preview_url = deezer.get_fresh_preview_url(track.id)
    if not preview_url:
        return None
    try:
        result = audio.analyze_preview(preview_url, deezer_bpm=track.bpm)
    except Exception:
        return None
    repo.upsert_audio_features(
        repo.AudioFeatures(
            track_id=track.id,
            bpm_verified=result.bpm,
            bpm_confidence=result.bpm_confidence,
            key=result.key,
            camelot=result.camelot,
            energy=result.energy,
        )
    )
    return result


@dataclass
class RankedResult:
    track: deezer.DeezerTrack
    breakdown: scoring.ScoreBreakdown


def _apply_diversity(ranked: list[RankedResult], max_per_artist: int) -> list[RankedResult]:
    per_artist: dict[int, int] = {}
    kept: list[RankedResult] = []
    for r in ranked:
        count = per_artist.get(r.track.artist_id, 0)
        if count >= max_per_artist:
            continue
        per_artist[r.track.artist_id] = count + 1
        kept.append(r)
    return kept


def run_match_pipeline(
    seed: deezer.DeezerTrack, result_count: int = config.RESULT_COUNT
) -> list[RankedResult]:
    """Full pipeline: gather -> hard-filter -> lazily analyze -> score ->
    diversify -> rank -> log. Returns up to `result_count` results; fewer
    if too few candidates survive filtering (never padded with bad matches)."""
    seed_features = _analyze_candidate(seed)
    seed_bpm = seed_features.bpm if seed_features else seed.bpm
    seed_camelot = seed_features.camelot if seed_features else None
    seed_energy = seed_features.energy if seed_features else None
    seed_tags = _get_tags(seed)

    pool = gather_candidate_pool(seed)
    pool = hard_filter_bpm(seed_bpm, pool)

    ranked: list[RankedResult] = []
    for candidate in pool:
        # Full detail persists the track (and resolves genre) before any
        # foreign-key-dependent write, and gives us the real album genre
        # for scoring instead of the coarser search-result stub.
        try:
            candidate = deezer.get_track_detail(candidate.id)
        except Exception:
            continue
        features = _analyze_candidate(candidate)
        if features is None:
            continue
        bpm = scoring.bpm_score(seed_bpm, features.bpm)
        key = scoring.key_score(seed_camelot, features.camelot)
        tags = scoring.tags_score(seed_tags, _get_tags(candidate))
        genre = scoring.genre_score(seed.genre, candidate.genre)
        energy = scoring.energy_score(seed_energy, features.energy)
        breakdown = scoring.total_score(bpm=bpm, key=key, tags=tags, genre=genre, energy=energy)
        ranked.append(RankedResult(track=candidate, breakdown=breakdown))

    ranked.sort(key=lambda r: r.breakdown.total, reverse=True)
    ranked = _apply_diversity(ranked, config.MAX_TRACKS_PER_ARTIST)
    top = ranked[:result_count]

    for r in top:
        repo.log_match_run(
            repo.MatchRun(
                seed_id=seed.id,
                candidate_id=r.track.id,
                bpm_score=r.breakdown.bpm,
                key_score=r.breakdown.key,
                tags_score=r.breakdown.tags,
                genre_score=r.breakdown.genre,
                energy_score=r.breakdown.energy,
                total_score=r.breakdown.total,
                label=r.breakdown.label,
            )
        )
    return top
