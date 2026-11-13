# api/intake.py — universal multipart intake (INTERFACE_CONTRACTS §2.1 ★ Phase 2)
import os
from pathlib import Path

import config
from typing import List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

router = APIRouter()

from services.limits import MAX_FILE_COUNT, MAX_FILE_SIZE, MAX_TOTAL_SIZE

MAX_FILES = MAX_FILE_COUNT
MAX_SIZE_PER_FILE_MB = MAX_FILE_SIZE // (1024 * 1024)
MAX_SIZE_TOTAL_MB = MAX_TOTAL_SIZE // (1024 * 1024)

def _spool_uploads(upload_files):
    """Write UploadFile bytes to spool files under the data directory.

    The extraction pipeline is path-based; multipart uploads are the byte
    channel (SEC-05 / D-009). Basename-sanitized names + a pid-unique prefix
    prevent clobbering and path traversal; the caller MUST unspool in a
    finally block.
    """
    upload_dir = Path(config.data_dir()) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    spooled, sizes = [], []
    for i, f in enumerate(upload_files):
        base = os.path.basename(f.filename or f"upload_{i}.bin")
        if not base or base in {".", ".."}:
            base = f"upload_{i}.bin"
        dest = upload_dir / f"{os.getpid()}~{i}~{base}"
        with open(dest, "wb") as out:
            out.write(f.file.read())
        size = dest.stat().st_size
        if size > MAX_SIZE_PER_FILE_MB * 1024 * 1024:
            os.remove(dest)
            raise HTTPException(413, f"File too large (max {MAX_SIZE_PER_FILE_MB} MB per file)")
        spooled.append(str(dest))
        sizes.append(size)
    return spooled, sizes

def _unspool(spooled):
    for p in spooled:
        try:
            os.remove(p)
        except OSError:
            pass

from intake import universal_intake as _universal_intake

@router.post("/intake")
async def universal_intake(
    files: List[UploadFile] = File(None),
    policy: str = Form("review_first"),
):
    """Universal multipart intake: 6 formats → staged review queue.

    Server receives **bytes**, never filesystem paths (SEC-05 / D-009).
    """
    incoming = files or []
    if not incoming:
        raise HTTPException(400, "No files provided")
    if len(incoming) > MAX_FILES:
        raise HTTPException(400, f"Too many files (max {MAX_FILES})")

    # size caps (per-file checked in _spool_uploads; total here)
    total_bytes = sum((getattr(f, "size", None) or 0) for f in incoming)
    if total_bytes > MAX_SIZE_TOTAL_MB * 1024 * 1024:
        raise HTTPException(413, f"Payload too large (max {MAX_SIZE_TOTAL_MB} MB)")

    # Multipart uploads: spool bytes → path-based pipeline → guaranteed cleanup
    spooled = None
    try:
        spooled, spool_sizes = _spool_uploads(incoming)
        spool_total = sum(spool_sizes)
        if spool_total > MAX_SIZE_TOTAL_MB * 1024 * 1024:
            raise HTTPException(413, f"Payload too large (max {MAX_SIZE_TOTAL_MB} MB)")
        result = await _universal_intake(spooled,
                                         chain=config.load().get("chain", []))
    finally:
        if spooled:
            _unspool(spooled)
    return result