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

    # size caps (per-file from UploadFile.size when known; total below)
    total_bytes = sum((getattr(f, "size", None) or 0) for f in incoming)
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

    # Multipart uploads: spool bytes → path-based pipeline → guaranteed cleanup
    if files:
        spooled = None
        try:
            spooled, spool_sizes = _spool_uploads(files)
            spool_total = sum(spool_sizes)
            if spool_total > MAX_SIZE_TOTAL_MB * 1024 * 1024:
                raise HTTPException(413, f"Payload too large (max {MAX_SIZE_TOTAL_MB} MB)")
            result = await _universal_intake(spooled,
                                             chain=config.load().get("chain", []))
        finally:
            if spooled:
                _unspool(spooled)
        return result
    result = await _universal_intake(paths or [], chain=config.load().get("chain", []))
    return result