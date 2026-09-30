"""In-memory job tracking for long-running work (match runs, mix-snippet
rendering). No persistence -- jobs are lost on server restart, which is
fine for a single-user local tool. Each job runs in a background thread
so the HTTP request that started it can return immediately with a job_id.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_lock = threading.Lock()
_jobs: dict[str, "Job"] = {}


@dataclass
class Job:
    id: str
    status: str = "queued"  # queued | running | done | error
    progress: str = ""
    result: Any = None
    error: Optional[str] = None


def create_job(work: Callable[["Job"], Any]) -> str:
    """Runs `work(job)` in a background thread. `work` should mutate
    `job.progress` as it goes and return the final result."""
    job = Job(id=str(uuid.uuid4()))
    with _lock:
        _jobs[job.id] = job

    def _run() -> None:
        job.status = "running"
        try:
            job.result = work(job)
            job.status = "done"
        except Exception as exc:
            job.status = "error"
            job.error = str(exc)

    threading.Thread(target=_run, daemon=True).start()
    return job.id


def get_job(job_id: str) -> Optional[Job]:
    with _lock:
        return _jobs.get(job_id)
