"""GET /api/preview/{track_id} -- server fetches a fresh Deezer preview
URL and streams the audio. Deezer preview URLs are signed, expire, and
may block cross-origin playback, so the browser never sees the raw URL.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from sources import deezer

router = APIRouter()


@router.get("/preview/{track_id}")
def preview(track_id: int) -> StreamingResponse:
    try:
        url = deezer.get_fresh_preview_url(track_id)
    except deezer.DeezerAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not url:
        raise HTTPException(status_code=404, detail="No preview available for this track")

    def stream():
        with httpx.stream("GET", url, timeout=15.0, follow_redirects=True) as resp:
            for chunk in resp.iter_bytes():
                yield chunk

    return StreamingResponse(stream(), media_type="audio/mpeg")
