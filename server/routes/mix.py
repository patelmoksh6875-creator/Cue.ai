"""POST /api/mix-snippet starts (or instantly resolves, if cached) a mix
snippet render job; GET /api/snippet/{id}.mp3 serves the result. See
mixing/render.py for the actual DSP pipeline and CLAUDE_HANDOFF_V2_WEB_UI.md
Section 6 for the design constraints.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from mixing import render
from server.jobs import create_job, get_job

router = APIRouter()


class MixRequest(BaseModel):
    a_id: int
    b_id: int
    style: str = "blend"
    length_seconds: int = render.DEFAULT_LENGTH_S
    source: str = "auto"      # auto | instrumental | beat_view | full_mix
    window_rank: int = 0      # 0 = best window pair; 1/2 = alternatives


def _result_payload(cache_key: str, info: dict) -> dict:
    return {"snippet_url": f"/api/snippet/{cache_key}.mp3", **info}


@router.post("/mix-snippet")
def mix_snippet(req: MixRequest) -> dict:
    if req.source not in render.SOURCES:
        raise HTTPException(status_code=400, detail=f"Unknown source '{req.source}'")
    cache_key = render.snippet_cache_key(
        req.a_id, req.b_id, req.style, req.length_seconds, req.source, req.window_rank
    )
    cached = render.load_cached_info(cache_key)
    if cached is not None:
        return {"job_id": None, **_result_payload(cache_key, cached)}

    def work(job) -> dict:
        job.progress = "Looking for instrumentals and rendering..."
        try:
            result = render.build_snippet(
                req.a_id, req.b_id, req.style, req.length_seconds, req.source, req.window_rank
            )
        except render.MixError as exc:
            raise RuntimeError(str(exc)) from exc
        return _result_payload(cache_key, result.info)

    return {"job_id": create_job(work), "snippet_url": None}


@router.get("/mix-snippet/{job_id}")
def poll_mix_snippet(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return {
        "status": job.status,
        "progress": job.progress,
        "result": job.result if job.status == "done" else None,
        "error": job.error,
    }


@router.get("/snippet/{snippet_id}.mp3")
def get_snippet(snippet_id: str) -> FileResponse:
    path = render.SNIPPET_DIR / f"{snippet_id}.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Snippet not found or not rendered yet")
    return FileResponse(path, media_type="audio/mpeg")
