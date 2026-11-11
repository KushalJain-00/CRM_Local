# api/history.py — processing history from the processed_files ledger.
# This is what the frontend showed as "/api/jobs/0" before: file name, status,
# contacts found, processed_at — straight from the per-file ledger the pipeline writes.
import logging
import os
import sqlite3

from fastapi import APIRouter, Query

import config as _config

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_ROWS = 500


def _get_con():
    con = sqlite3.connect(_config.db_path("crm"), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


@router.get("/history")
async def list_history(limit: int = Query(_MAX_ROWS, ge=1, le=_MAX_ROWS)):
    con = _get_con()
    try:
        rows = con.execute(
            "SELECT path, status, detail, contacts_found, processed_at"
            " FROM processed_files"
            " ORDER BY processed_at IS NULL, processed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        results = []
        for r in rows:
            path = r["path"] or ""
            results.append({
                "file": os.path.basename(path) or path,
                "path": path,
                "status": (r["status"] or "unknown"),
                "detail": r["detail"],
                "contacts_found": r["contacts_found"] or 0,
                "processed_at": r["processed_at"],
            })
        return {"results": results, "total": len(results)}
    finally:
        con.close()
