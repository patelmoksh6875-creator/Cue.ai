"""GET /api/search?q= -- Deezer search for picking a seed song."""
from __future__ import annotations

from fastapi import APIRouter

from sources import deezer

router = APIRouter()


@router.get("/search")
def search(q: str) -> list[dict]:
    if not q.strip():
        return []
    results = deezer.search_tracks(q, limit=10)
    return [
        {"id": t.id, "title": t.title, "artist": t.artist_name}
        for t in results
    ]
