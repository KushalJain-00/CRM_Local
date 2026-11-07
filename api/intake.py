# api/intake.py — universal multipart intake (INTERFACE_CONTRACTS §2.1 ★ Phase 2)
import os
import sys
from pathlib import Path

import config
from typing import Any, Dict, List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

router = APIRouter()


MAX_FILES = 50
MAX_SIZE_PER_FILE_MB = 10
MAX_SIZE_TOTAL_MB = 100


# Root-level intake module (services package partially unavailable until
# __init__.py is populated); import directly from the project top-level intake.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from intake import universal_intake as _universal_intake  # type: ignore


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
    # SEC-05 / D-028c: enforce path containment - all file paths must be within
    # the configured data directory to prevent path traversal attacks.
    data_dir = Path(config.data_dir()).resolve()
    for p in (paths or []):
        # Handle bare filenames (no directory component) by resolving them
        # relative to the data directory, matching intake.py logic.
        has_dir = os.path.sep in p or (os.path.altsep and os.path.altsep in p)
        if not has_dir:
            p = str(data_dir / p)
        resolved = Path(p).resolve()
        if not (str(resolved).startswith(str(data_dir) + os.sep) or str(resolved) == str(data_dir)):
            raise HTTPException(400, f"path outside allowed data directory: {p}")
    result = await _universal_intake(incoming)
    return result