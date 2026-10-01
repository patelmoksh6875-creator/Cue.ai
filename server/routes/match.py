"""POST /api/match starts a match run as a background job; GET
/api/match/{job_id} polls it. Returns config.RESULT_POOL results (not
just RESULT_COUNT) so the UI's filter bar can refill client-side.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config
from db import repo
from matching import candidates, scoring
from server.jobs import create_job, get_job
from sources import deezer

router = APIRouter()


class MatchRequest(BaseModel):
    seed_id: int


def _serialize_result(seed_bpm: Optional[float], r: candidates.RankedResult) -> dict:
    features = repo.get_audio_features(r.track.id)
    genre = candidates.resolve_display_genre(r.track)
    bpm_verified = features.bpm_verified if features else None
    return {
        "id": r.track.id,
        "title": r.track.title,
        "artist": r.track.artist_name,
        "genre": genre,
        "bpm": round(bpm_verified) if bpm_verified else None,
        "bpm_confidence": (
            round(features.bpm_confidence, 2)
            if features and features.bpm_confidence is not None
            else None
        ),
        "bpm_relation": scoring.bpm_relation(seed_bpm, bpm_verified),
        "camelot": features.camelot if features else None,
        "match_pct": scoring.percent_match(r.breakdown.total),
        "label": r.breakdown.label,
        "breakdown_pct": {
            "bpm": scoring.percent_match(r.breakdown.bpm) if r.breakdown.bpm is not None else None,
            "key": scoring.percent_match(r.breakdown.key) if r.breakdown.key is not None else None,
            "tags": scoring.percent_match(r.breakdown.tags) if r.breakdown.tags is not None else None,
            "genre": scoring.percent_match(r.breakdown.genre) if r.breakdown.genre is not None else None,
            "energy": scoring.percent_match(r.breakdown.energy) if r.breakdown.energy is not None else None,
        },
    }


@router.post("/match")
def start_match(req: MatchRequest) -> dict:
    try:
        seed = deezer.get_track_detail(req.seed_id)
    except deezer.DeezerAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    def work(job) -> dict:
        job.progress = "Gathering candidates..."

        def on_progress(done: int, total: int) -> None:
            job.progress = f"Analyzing candidates ({done}/{total})..."

        results = candidates.run_match_pipeline(
            seed, result_count=config.RESULT_POOL, progress_callback=on_progress
        )
        seed_features = repo.get_audio_features(seed.id)
        seed_bpm = seed_features.bpm_verified if seed_features else seed.bpm
        seed_genre = candidates.resolve_display_genre(seed)
        return {
            "seed": {
                "id": seed.id,
                "title": seed.title,
                "artist": seed.artist_name,
                "genre": seed_genre,
                "bpm": round(seed_bpm) if seed_bpm else None,
                "camelot": seed_features.camelot if seed_features else None,
            },
            "result_count_requested": config.RESULT_COUNT,
            "results": [_serialize_result(seed_bpm, r) for r in results],
        }

    job_id = create_job(work)
    return {"job_id": job_id}


@router.get("/match/{job_id}")
def poll_match(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return {
        "status": job.status,
        "progress": job.progress,
        "result": job.result if job.status == "done" else None,
        "error": job.error,
    }
