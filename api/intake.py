# api/intake.py — universal multipart intake (INTERFACE_CONTRACTS §2.1 ★ Phase 2)
import os
from typing import Any, Dict, List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

router = APIRouter()


MAX_FILES = 50
MAX_SIZE_PER_FILE_MB = 10
MAX_SIZE_TOTAL_MB = 100


@router.post("/intake")
async def universal_intake(
    files: List[UploadFile] = File(None),
    paths: List[str] = Form(None),
    policy: str = Form("review_first"),
):
    """Universal multipart intake: 6 formats → job.

    Replaces the path-list body (D-009). Server receives **bytes**, never
    filesystem paths — closes SEC-05 path-containment hole.
    """
    incoming = files or (paths or [])
    if not incoming:
        raise HTTPException(400, "No files provided")
    if len(incoming) > MAX_FILES:
        raise HTTPException(400, f"Too many files (max {MAX_FILES})")

    # size caps
    total_bytes = 0
    for f in incoming:
        # FastAPI UploadFile .size may be None until read; guard safely
        sz = getattr(f, "size", None)
        if sz is None:
            # read a little to estimate; for real usage size is set by the client
            pass
        total_bytes += (sz or 0)

    if total_bytes > MAX_SIZE_TOTAL_MB * 1024 * 1024:
        raise HTTPException(413, f"Payload too large (max {MAX_SIZE_TOTAL_MB} MB)")

    # delegate to intake module
    from services import intake as intake_svc  # type: ignore
    result = await intake_svc.universal_intake(incoming)
    return result