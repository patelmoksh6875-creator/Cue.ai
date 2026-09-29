"""All Deezer API calls live here. No other module should know Deezer
exists — swapping the source is a one-file change.

Deezer's public API needs no auth key. Docs: https://developers.deezer.com/api
Rate limit is roughly 50 requests / 5 seconds per IP (config.DEEZER_MAX_REQUESTS).
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

import config
from db import repo

logger = logging.getLogger(__name__)

_client = httpx.Client(base_url=config.DEEZER_BASE_URL, timeout=10.0)

# Sliding-window throttle: track request timestamps, sleep if we'd exceed
# DEEZER_MAX_REQUESTS within DEEZER_PER_SECONDS.
_request_times: deque[float] = deque()


def _throttle() -> None:
    now = time.monotonic()
    window = config.DEEZER_PER_SECONDS
    while _request_times and now - _request_times[0] > window:
        _request_times.popleft()
    if len(_request_times) >= config.DEEZER_MAX_REQUESTS:
        sleep_for = window - (now - _request_times[0])
        if sleep_for > 0:
            time.sleep(sleep_for)
    _request_times.append(time.monotonic())


def _get(path: str, params: Optional[dict] = None, retries: int = 3) -> dict:
    last_error: Optional[Exception] = None
    for attempt in range(retries):
        _throttle()
        try:
            resp = _client.get(path, params=params)
            if resp.status_code == 429:
                logger.warning("Deezer rate limited on %s (attempt %d/%d)", path, attempt + 1, retries)
                time.sleep(2**attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "error" in data:
                raise DeezerAPIError(str(data["error"]))
            return data
        except (httpx.HTTPError, DeezerAPIError) as exc:
            last_error = exc
            logger.warning("Deezer request to %s failed (attempt %d/%d): %s", path, attempt + 1, retries, exc)
            time.sleep(2**attempt)
    logger.error("Deezer request to %s failed after %d retries -- is Deezer down?", path, retries)
    raise DeezerAPIError(
        f"Deezer request to {path} failed after {retries} retries -- Deezer may be down or "
        "rate-limiting this IP. Check https://developers.deezer.com for status."
    ) from last_error


class DeezerAPIError(Exception):
    pass


@dataclass
class DeezerTrack:
    id: int
    title: str
    artist_id: int
    artist_name: str
    album_id: Optional[int]
    duration: Optional[int]
    bpm: Optional[float]
    isrc: Optional[str]
    genre: Optional[str] = None
    # Transient only -- never persisted (db/repo.py has no such column,
    # since preview URLs are signed and expire). Carries the preview URL
    # a /track/{id} call already returned, so callers in the same request
    # chain don't have to immediately re-fetch it a few seconds later.
    preview_url: Optional[str] = None


def _normalize_track(raw: dict, genre: Optional[str] = None) -> DeezerTrack:
    artist = raw.get("artist", {})
    album = raw.get("album", {})
    bpm = raw.get("bpm")
    return DeezerTrack(
        id=raw["id"],
        title=raw.get("title", ""),
        artist_id=artist.get("id"),
        artist_name=artist.get("name", ""),
        album_id=album.get("id"),
        duration=raw.get("duration"),
        bpm=float(bpm) if bpm else None,
        isrc=raw.get("isrc"),
        genre=genre,
        preview_url=raw.get("preview") or None,
    )


def search_tracks(query: str, limit: int = 10) -> list[DeezerTrack]:
    """Search for tracks by free-text query. Returns normalized tracks
    (does not fetch full detail/BPM — call get_track_detail for that)."""
    data = _get("/search", params={"q": query, "limit": limit})
    return [_normalize_track(item) for item in data.get("data", [])]


def get_track_detail(track_id: int) -> DeezerTrack:
    """Fetch full track detail including BPM and ISRC, resolve album genre,
    and persist everything through repo.py."""
    raw = _get(f"/track/{track_id}")
    genre = None
    album = raw.get("album", {})
    if album.get("id"):
        try:
            genre = get_album_genre(album["id"])
        except DeezerAPIError:
            genre = None
    track = _normalize_track(raw, genre=genre)
    _persist_track(track, album_title=album.get("title", ""))
    return track


def _persist_track(track: DeezerTrack, album_title: str = "") -> None:
    repo.upsert_artist(repo.Artist(id=track.artist_id, name=track.artist_name))
    if track.album_id:
        # get_album_genre() (called above) already upserted the real title
        # when it looked up the album; only overwrite it here if we
        # actually have one, so this call can never blank it out.
        existing = repo.get_album(track.album_id)
        title = album_title or (existing.title if existing else "")
        repo.upsert_album(repo.Album(id=track.album_id, title=title, genre=track.genre))
    repo.upsert_track(
        repo.Track(
            id=track.id,
            title=track.title,
            artist_id=track.artist_id,
            album_id=track.album_id,
            isrc=track.isrc,
            duration=track.duration,
            deezer_bpm=track.bpm,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
    )


def get_album_genre(album_id: int) -> Optional[str]:
    """Deezer stores genre at the album level. Cache-check first."""
    cached = repo.get_album(album_id)
    if cached is not None and cached.genre:
        return cached.genre
    raw = _get(f"/album/{album_id}")
    genres = raw.get("genres", {}).get("data", [])
    genre = genres[0]["name"] if genres else None
    repo.upsert_album(repo.Album(id=album_id, title=raw.get("title", ""), genre=genre))
    return genre


def get_artist_related(artist_id: int, limit: int = 25) -> list[DeezerTrack]:
    """Top tracks by artists related to the given artist (candidate source)."""
    related = _get(f"/artist/{artist_id}/related", params={"limit": 10})
    tracks: list[DeezerTrack] = []
    for artist in related.get("data", []):
        top = _get(f"/artist/{artist['id']}/top", params={"limit": limit // 10 or 1})
        tracks.extend(_normalize_track(item) for item in top.get("data", []))
    return tracks


def get_chart_tracks(genre_id: int = 0, limit: int = 50) -> list[DeezerTrack]:
    """Chart tracks for a genre (0 = global chart) as a candidate source."""
    data = _get(f"/chart/{genre_id}/tracks", params={"limit": limit})
    return [_normalize_track(item) for item in data.get("data", [])]


def get_fresh_preview_url(track_id: int) -> Optional[str]:
    """Preview URLs are signed and expire — always fetch fresh, never store."""
    raw = _get(f"/track/{track_id}")
    return raw.get("preview") or None
