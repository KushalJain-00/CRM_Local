"""Multipart intake and folder scans."""
import ntpath
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

import config
import pipeline
from api import jobs
from intake import universal_intake as _universal_intake
from services.limits import MAX_FILE_COUNT, MAX_FILE_SIZE, MAX_TOTAL_SIZE

router = APIRouter()
ImportPolicy = Literal["review_first", "always_stage", "smart_import"]


async def _spool_uploads(files, directory):
    paths, names = [], []
    total = 0
    for index, upload in enumerate(files):
        name = ntpath.basename(upload.filename or "") or f"upload_{index}.bin"
        suffix = Path(name).suffix.lower()
        if suffix not in {".xlsx", ".xls", ".csv", ".pdf", ".txt", ".eml"}:
            suffix = ".bin"
        path = Path(directory) / f"{index}{suffix}"
        size = 0
        with path.open("wb") as out:
            while chunk := await upload.read(64 * 1024):
                size += len(chunk)
                total += len(chunk)
                if size > MAX_FILE_SIZE or total > MAX_TOTAL_SIZE:
                    raise HTTPException(413, "Upload exceeds the per-file or batch size limit")
                out.write(chunk)
        paths.append(str(path))
        names.append(name)
    return paths, names


@router.post("/intake")
async def universal_intake(
    files: list[UploadFile] = File(None),
    policy: ImportPolicy | None = Form(None),
):
    """Stage uploaded files and keep the existing synchronous result shape."""
    if not files:
        raise HTTPException(400, "No files provided")
    if len(files) > MAX_FILE_COUNT:
        raise HTTPException(400, f"Too many files (max {MAX_FILE_COUNT})")
    if (any((file.size or 0) > MAX_FILE_SIZE for file in files)
            or sum(file.size or 0 for file in files) > MAX_TOTAL_SIZE):
        raise HTTPException(413, "Upload exceeds the per-file or batch size limit")

    cfg = config.load()
    with TemporaryDirectory(prefix="intake-", dir=config.data_dir()) as directory:
        paths, names = await _spool_uploads(files, directory)
        job = jobs.start("intake", len(paths))
        try:
            result = await _universal_intake(
                paths, chain=cfg["chain"], cfg=cfg, source_names=names,
                options={"policy": policy}, job=job,
            )
        finally:
            jobs.finish(job, succeeded=job["completed"] == len(paths))
    return {**result, "job_id": job["job_id"], "state": job["state"]}


@router.post("/scan")
async def scan():
    return await pipeline.scan()
