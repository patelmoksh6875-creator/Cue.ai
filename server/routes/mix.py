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


@router.post("/mix-snippet")
def mix_snippet(req: MixRequest) -> dict:
    cache_key = render.snippet_cache_key(req.a_id, req.b_id, req.style, req.length_seconds)
    if render.snippet_path(cache_key).exists():
        return {"job_id": None, "snippet_url": f"/api/snippet/{cache_key}.mp3"}

    def work(job) -> dict:
        job.progress = "Rendering mix snippet..."
        try:
            result = render.build_snippet(req.a_id, req.b_id, req.style, req.length_seconds)
        except render.MixError as exc:
            raise RuntimeError(str(exc)) from exc
        return {
            "snippet_url": f"/api/snippet/{cache_key}.mp3",
            "warnings": {
                "stretch_exceeds_quality": result.warnings.stretch_exceeds_quality,
                "stretch_pct": result.warnings.stretch_pct,
                "key_incompatible": result.warnings.key_incompatible,
                "low_confidence_bpm": result.warnings.low_confidence_bpm,
            },
            "note": (
                "This is a sample of how the two previews sound together, not the "
                "real transition point in the full tracks -- Deezer previews are a "
                "30s clip from somewhere in the song, not the actual intro/outro."
            ),
        }

    job_id = create_job(work)
    return {"job_id": job_id, "snippet_url": None}


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
