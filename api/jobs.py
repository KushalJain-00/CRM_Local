# api/jobs.py — job registry (INTERFACE_CONTRACTS §2.1 ★ Phase 2)
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

router = APIRouter()

# In-memory job store: survives only within a process.
# Phase 3 will promote to ledger-backed (processed_files / extraction_runs).
_jobs: Dict[int, Dict[str, Any]] = {}
_next_id = 1


@router.get("/jobs")
async def list_jobs():
    """Return summary of all known jobs."""
    return {"jobs": list(_jobs.values())}


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: int):
    """Poll job status.

    Stub → real extraction logic wired in P2-2.
    """
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: int):
    """Best-effort cancel. Files already staged stay staged."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    job["state"] = "cancelling"
    return {"job_id": job_id, "state": "cancelling"}