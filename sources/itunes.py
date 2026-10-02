"""ALL iTunes Search API calls live here. Public, no key; soft limit of
roughly 20 requests/minute (config.ITUNES_MAX_REQUESTS per
ITUNES_PER_SECONDS). Docs: https://performance-partners.apple.com/search-api
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import httpx

import config

logger = logging.getLogger(__name__)
_client = httpx.Client(base_url=config.ITUNES_BASE_URL, timeout=10.0)
_request_times: deque[float] = deque()


class ItunesError(Exception):
    pass


@dataclass
class ItunesTrack:
    id: int
    title: str
    artist: str
    album: str
    duration_s: Optional[int]
    preview_url: Optional[str]


def _throttle() -> None:
    now = time.monotonic()
    while _request_times and now - _request_times[0] > config.ITUNES_PER_SECONDS:
        _request_times.popleft()
    if len(_request_times) >= config.ITUNES_MAX_REQUESTS:
        time.sleep(max(0.0, config.ITUNES_PER_SECONDS - (now - _request_times[0])))
    _request_times.append(time.monotonic())


def _get(path: str, params: dict) -> dict:
    _throttle()
    try:
        resp = _client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("iTunes request %s failed: %s", path, exc)
        raise ItunesError(f"iTunes is unreachable or returned an error for {path}: {exc}") from exc


def _normalize(raw: dict) -> ItunesTrack:
    ms = raw.get("trackTimeMillis")
    return ItunesTrack(
        id=raw["trackId"],
        title=raw.get("trackName", ""),
        artist=raw.get("artistName", ""),
        album=raw.get("collectionName", ""),
        duration_s=round(ms / 1000) if ms else None,
        preview_url=raw.get("previewUrl"),
    )


def search_songs(term: str, limit: int = 15) -> list[ItunesTrack]:
    data = _get("/search", {"term": term, "entity": "song", "limit": limit})
    return [_normalize(r) for r in data.get("results", []) if "trackId" in r]


def get_fresh_preview_url(track_id: int) -> Optional[str]:
    """Re-fetch by ID instead of storing a URL (previews can move/expire)."""
    data = _get("/lookup", {"id": track_id})
    results = data.get("results", [])
    return results[0].get("previewUrl") if results else None
