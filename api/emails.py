# api/emails.py — eml_emails listing with per-email extracted-contact counts.
# contact_count = contacts the pipeline extracted from that email (email_staged_links).
import logging
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

import config as _config

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_SIZE = 500
_DEFAULT_SIZE = 25


def _get_con():
    con = sqlite3.connect(_config.db_path("crm"), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _link_table(con) -> Optional[str]:
    for table in ("email_staged_links", "contact_emails"):
        if con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            return table
    return None


@router.get("/emails")
async def list_emails(
    page: int = Query(1, ge=1),
    size: int = Query(_DEFAULT_SIZE, ge=1, le=_MAX_SIZE),
    q: Optional[str] = None,
):
    con = _get_con()
    try:
        where, params = "1=1", []
        if q and q.strip():
            like = f"%{q.strip()}%"
            where = "(subject LIKE ? OR sender_name LIKE ? OR sender_email LIKE ?)"
            params = [like, like, like]
        link_table = _link_table(con)
        if link_table:
            count_sql = f"(SELECT COUNT(*) FROM {link_table} l WHERE l.email_id = e.id)"
        else:  # pre-v3 schema: no link tables yet — 0, never a fabricated number
            count_sql = "0"
        total = con.execute(
            f"SELECT count(*) FROM eml_emails WHERE {where}", params).fetchone()[0]
        rows = con.execute(
            f"SELECT e.id, e.subject, e.sender_name, e.sender_email, e.date,"
            f"       e.file_name, e.processed_at, {count_sql} AS contact_count"
            f" FROM eml_emails e WHERE {where}"
            " ORDER BY e.date IS NULL, e.date DESC, e.id DESC LIMIT ? OFFSET ?",
            params + [size, (page - 1) * size],
        ).fetchall()
        return {"rows": [dict(r) for r in rows], "total": total, "page": page,
                "pageSize": size,
                "totalPages": (total + size - 1) // size if total else 0}
    finally:
        con.close()
