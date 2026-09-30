"""POST /api/mix-snippet and GET /api/snippet/{id}.mp3 -- mix snippet
maker. Implemented in a later stage (see CLAUDE_HANDOFF_V2_WEB_UI.md
Section 6); stubbed here so the API contract exists and the frontend can
be built against it before the DSP work lands.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class MixRequest(BaseModel):
    a_id: int
    b_id: int
    style: str = "blend"
    length_seconds: int = 12


@router.post("/mix-snippet")
def mix_snippet(req: MixRequest) -> dict:
    raise HTTPException(status_code=501, detail="Mix snippet maker not implemented yet")


@router.get("/snippet/{snippet_id}.mp3")
def get_snippet(snippet_id: str):
    raise HTTPException(status_code=501, detail="Mix snippet maker not implemented yet")
