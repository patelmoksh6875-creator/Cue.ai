"""GET /api/search?q= -- Deezer search for picking a seed song."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from sources import deezer

router = APIRouter()


@router.get("/search")
def search(q: str) -> list[dict]:
    if not q.strip():
        return []
    try:
        results = deezer.search_tracks(q, limit=10)
    except deezer.DeezerAPIError as exc:
        # Previously uncaught here (unlike match.py/preview.py, which
        # already did this) -- Deezer being unreachable or rate-limited
        # surfaced as FastAPI's generic 500, which the frontend showed
        # as an unhelpful "fetch error" instead of a specific one.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [
        {"id": t.id, "title": t.title, "artist": t.artist_name}
        for t in results
    ]
