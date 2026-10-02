"""FastAPI app: route registration and static file serving. Route
handlers are thin -- they call sources/analysis/matching/db/agent and
return JSON. No SQL, no external API calls, and no scoring logic live
here.

Binds to 127.0.0.1 only (see cue.py for how it's launched). API keys
never reach the browser: every external call happens in sources/ or
agent/, server-side.
"""
from __future__ import annotations

import os
import signal
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from db import repo
from mixing import render as mix_render
from server.routes import health, match, mix, preview, search

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    repo.init_db()
    yield
    # Personal use only: don't leave a persistent library of derived
    # preview audio sitting around between runs.
    mix_render.cleanup_snippet_cache()


app = FastAPI(title="Cue", lifespan=_lifespan)
logger = logging.getLogger("cue.server")


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """Never return a bare "Internal Server Error": log the full traceback
    to logs/cue.log and tell the UI what actually failed."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Server error ({type(exc).__name__}: {exc}). See logs/cue.log or run: python cue.py logs"},
    )

app.include_router(health.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(match.router, prefix="/api")
app.include_router(preview.router, prefix="/api")
app.include_router(mix.router, prefix="/api")


@app.post("/api/shutdown")
def shutdown() -> dict:
    """Cleanly stops the server. Sends itself SIGTERM a moment after
    responding, so uvicorn can shut down gracefully (its default SIGTERM
    handler) rather than having a request handler kill the process it's
    running in mid-response."""

    def _stop() -> None:
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Timer(0.3, _stop).start()
    return {"status": "stopping"}


# Mounted last so /api/* routes above take priority over static files.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
