"""All Last.fm API calls live here. No other module should know Last.fm
exists. Requires a free API key (config.LASTFM_API_KEY) -- get one at
https://www.last.fm/api/account/create. Verify these endpoint names
against current docs if Last.fm has changed anything:
https://www.last.fm/api/show/track.getTopTags
https://www.last.fm/api/show/track.getSimilar
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import httpx

import config

_client = httpx.Client(base_url=config.LASTFM_BASE_URL, timeout=10.0)
_request_times: deque[float] = deque()


class LastFMError(Exception):
    pass


class LastFMNotConfigured(LastFMError):
    """Raised when no API key is set. Callers should catch this and fall
    back to genre-only matching rather than crash the whole pipeline."""


def _throttle() -> None:
    now = time.monotonic()
    window = config.LASTFM_PER_SECONDS
    while _request_times and now - _request_times[0] > window:
        _request_times.popleft()
    if len(_request_times) >= config.LASTFM_MAX_REQUESTS:
        sleep_for = window - (now - _request_times[0])
        if sleep_for > 0:
            time.sleep(sleep_for)
    _request_times.append(time.monotonic())


def _get(method: str, params: dict, retries: int = 3) -> dict:
    if not config.LASTFM_API_KEY:
        raise LastFMNotConfigured("LASTFM_API_KEY is not set")

    query = {
        "method": method,
        "api_key": config.LASTFM_API_KEY,
        "format": "json",
        **params,
    }
    last_error: Exception | None = None
    for attempt in range(retries):
        _throttle()
        try:
            resp = _client.get("", params=query)
            if resp.status_code == 429:
                time.sleep(2**attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "error" in data:
                raise LastFMError(f"Last.fm error {data['error']}: {data.get('message')}")
            return data
        except (httpx.HTTPError, LastFMError) as exc:
            last_error = exc
            time.sleep(2**attempt)
    raise LastFMError(f"Last.fm request {method} failed after {retries} retries") from last_error


@dataclass
class SimilarTrack:
    title: str
    artist: str
    match: float  # Last.fm's own 0..1 similarity score


def get_top_tags(artist: str, title: str, limit: int = 10) -> list[tuple[str, float]]:
    """Crowd tags for a track, normalized to (tag, weight 0..1). Returns
    an empty list (not an error) if the track has no tags -- Last.fm tags
    are notoriously sparse for obscure tracks."""
    data = _get("track.getTopTags", {"artist": artist, "track": title})
    tags = data.get("toptags", {}).get("tag", [])
    if not tags:
        return []
    max_count = max((int(t.get("count", 0)) for t in tags), default=1) or 1
    return [(t["name"], int(t.get("count", 0)) / max_count) for t in tags[:limit]]


def get_similar_tracks(artist: str, title: str, limit: int = 30) -> list[SimilarTrack]:
    """Candidate discovery: tracks Last.fm considers similar to the seed."""
    data = _get("track.getSimilar", {"artist": artist, "track": title, "limit": limit})
    tracks = data.get("similartracks", {}).get("track", [])
    return [
        SimilarTrack(
            title=t["name"],
            artist=t["artist"]["name"],
            match=float(t.get("match", 0.0)),
        )
        for t in tracks
    ]
