"""Find an OFFICIAL instrumental for a track (Deezer first, then iTunes).

A candidate is accepted only if it is confidently the same recording
without vocals: title says "instrumental" AND matches the original once
that word/parentheticals are stripped, artist matches, and the duration is
close. Karaoke, tribute, cover, "in the style of", lullaby/piano/orchestral
covers and remixes are rejected outright. Below config.INSTRUMENTAL_MIN_CONFIDENCE
the answer is "none found". Results (including negatives) are cached in
instrumental_links; negatives are re-checked after a TTL.

Limits: official instrumentals don't exist for every song.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import config
from db import repo
from sources import deezer, itunes

_REJECT = re.compile(
    r"karaoke|tribute|\bcover\b|in the style of|originally performed|made famous|"
    r"lullaby|lullabies|piano (version|cover|tribute)|orchestra|string quartet|"
    r"\bremix\b|\brework\b|\bbootleg\b|\bmashup\b|backing track|sing[- ]?along|"
    r"8[- ]?bit|music box|\bvip\b|\bflip\b|acoustic version|\blive\b|"
    r"as made famous|performed by|\bmedley\b",
    re.IGNORECASE,
)
_INSTRUMENTAL = re.compile(r"\binstrumental\b", re.IGNORECASE)
_BRACKETS = re.compile(r"[\(\[\{].*?[\)\]\}]")
_FEAT = re.compile(r"\b(feat\.?|ft\.?|featuring|with)\b.*$", re.IGNORECASE)


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def normalize(text: str) -> str:
    t = _ascii(text).lower()
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def base_title(title: str) -> str:
    """Title without parentheticals, feat. credits and the word 'instrumental'."""
    t = _BRACKETS.sub(" ", title)
    t = _INSTRUMENTAL.sub(" ", t)
    t = _FEAT.sub(" ", t)
    t = re.sub(r"\s-\s.*$", "", t)  # "Song - Instrumental" style suffixes
    return normalize(t)


def _artist_tokens(artist: str) -> set[str]:
    parts = re.split(r",|&|\band\b|\bx\b|;|\bfeat\.?\b|\bft\.?\b|\bwith\b", _ascii(artist).lower())
    return {normalize(p) for p in parts if normalize(p)}


def artist_similarity(original: str, candidate: str) -> float:
    a, b = _artist_tokens(original), _artist_tokens(candidate)
    if not a or not b:
        return 0.0
    if a & b:
        return 1.0
    return max(difflib.SequenceMatcher(None, x, y).ratio() for x in a for y in b)


@dataclass
class Candidate:
    source: str  # "deezer" | "itunes"
    source_track_id: str
    title: str
    artist: str
    duration: Optional[int]
    album: str = ""


def score_candidate(
    original_title: str, original_artist: str, original_duration: Optional[int], cand: Candidate
) -> float:
    """0.0 means rejected; otherwise a confidence in (0, 1]."""
    if not _INSTRUMENTAL.search(cand.title):
        return 0.0
    # Reject on the candidate's own title/artist/album, but allow the word
    # "remix"/"live" etc. if the ORIGINAL title has it too (e.g. a remix seed).
    text = f"{cand.title} {cand.artist} {cand.album}"
    for m in _REJECT.finditer(text):
        if not re.search(re.escape(m.group(0)), original_title, re.IGNORECASE):
            return 0.0
    title_sim = difflib.SequenceMatcher(None, base_title(original_title), base_title(cand.title)).ratio()
    if title_sim < 0.85:
        return 0.0
    art_sim = artist_similarity(original_artist, cand.artist)
    if art_sim < 0.8:
        return 0.0
    dur_score = 0.5  # unknown duration: neither reward nor reject
    if original_duration and cand.duration:
        diff = abs(original_duration - cand.duration)
        if diff > config.INSTRUMENTAL_DURATION_TOLERANCE_S:
            return 0.0
        dur_score = 1.0 - diff / config.INSTRUMENTAL_DURATION_TOLERANCE_S
    return round(0.5 * title_sim + 0.3 * art_sim + 0.2 * dur_score, 3)


def best_candidate(
    original_title: str, original_artist: str, original_duration: Optional[int],
    candidates: list[Candidate],
) -> Optional[tuple[Candidate, float]]:
    scored = [(c, score_candidate(original_title, original_artist, original_duration, c)) for c in candidates]
    scored = [x for x in scored if x[1] >= config.INSTRUMENTAL_MIN_CONFIDENCE]
    return max(scored, key=lambda x: x[1]) if scored else None


def _queries(title: str, artist: str) -> list[str]:
    clean = _BRACKETS.sub(" ", title).strip()
    clean = _FEAT.sub("", clean).strip()
    first_artist = re.split(r",|&| x | feat", artist)[0].strip()
    qs = [f"{title} {first_artist} instrumental", f"{clean} {first_artist} instrumental"]
    seen, out = set(), []
    for q in qs:
        q = re.sub(r"\s+", " ", q).strip()
        if q.lower() not in seen:
            seen.add(q.lower()); out.append(q)
    return out


def _deezer_candidates(queries: list[str]) -> list[Candidate]:
    out: list[Candidate] = []
    for q in queries:
        for t in deezer.search_tracks(q, limit=15):
            out.append(Candidate("deezer", str(t.id), t.title, t.artist_name, t.duration))
    return out


def _itunes_candidates(queries: list[str]) -> list[Candidate]:
    out: list[Candidate] = []
    for q in queries:
        for t in itunes.search_songs(q, limit=15):
            out.append(Candidate("itunes", str(t.id), t.title, t.artist, t.duration_s, t.album))
    return out


def _negative_is_fresh(link: repo.InstrumentalLink) -> bool:
    try:
        checked = datetime.fromisoformat(link.checked_at)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - checked < timedelta(days=config.INSTRUMENTAL_NEGATIVE_TTL_DAYS)


def find_instrumental(track: deezer.DeezerTrack) -> Optional[repo.InstrumentalLink]:
    """On-demand lookup (called when Preview mix is clicked, never for every
    candidate up front -- rate limits). Returns the cached link or None."""
    cached = repo.get_instrumental_link(track.id)
    if cached is not None:
        if cached.found:
            return cached
        if _negative_is_fresh(cached):
            return None

    queries = _queries(track.title, track.artist_name)
    match = None
    for gather in (_deezer_candidates, _itunes_candidates):  # Deezer first, then iTunes
        try:
            cands = gather(queries)
        except (deezer.DeezerAPIError, itunes.ItunesError):
            continue  # one source being down shouldn't hide the other
        match = best_candidate(track.title, track.artist_name, track.duration, cands)
        if match:
            break

    if match is None:
        repo.upsert_instrumental_link(repo.InstrumentalLink(track_id=track.id, found=False))
        return None
    cand, conf = match
    link = repo.InstrumentalLink(
        track_id=track.id, found=True, source=cand.source, source_track_id=cand.source_track_id,
        title=cand.title, artist=cand.artist, duration=cand.duration, confidence=conf,
    )
    repo.upsert_instrumental_link(link)
    return link


def instrumental_preview_url(link: repo.InstrumentalLink) -> Optional[str]:
    """Fresh preview URL for a cached link (never stored -- they expire)."""
    if link.source == "deezer":
        return deezer.get_fresh_preview_url(int(link.source_track_id))
    if link.source == "itunes":
        return itunes.get_fresh_preview_url(int(link.source_track_id))
    return None
