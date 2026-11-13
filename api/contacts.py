# api/contacts.py — canonical contacts list/search/edit (D-032: user-authored
# CRUD only; file intake writes via staging approval, D-007).
import logging
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import db
from services.keys import record_keys

logger = logging.getLogger(__name__)
router = APIRouter()

_SORT_ALLOWLIST = {"id", "name", "email_primary", "phone_primary", "company", "created_at"}
_MAX_SIZE = 1000
_DEFAULT_SIZE = 25
_EDITABLE_FIELDS = {
    "name", "email_primary", "email_secondary", "phone_primary", "phone_secondary",
    "company", "designation", "address", "city", "pincode", "website",
    "whatsapp", "position", "files", "products_misc",
}


class ContactFieldsIn(BaseModel):
    fields: dict




def _has_deleted_at(con) -> bool:
    return any(r[1] == "deleted_at" for r in con.execute("PRAGMA table_info(contacts)").fetchall())


def _live_clause(con) -> str:
    return "deleted_at IS NULL" if _has_deleted_at(con) else "1=1"


@router.get("/contacts")
async def list_contacts(
    page: int = Query(1, ge=1),
    size: int = Query(_DEFAULT_SIZE, ge=1, le=_MAX_SIZE),
    q: Optional[str] = None,
    sort: str = Query("id"),
    dir: str = Query("desc"),
):
    if sort not in _SORT_ALLOWLIST:
        raise HTTPException(422, f"sort must be one of {sorted(_SORT_ALLOWLIST)}")
    if dir not in ("asc", "desc"):
        raise HTTPException(422, "dir must be 'asc' or 'desc'")
    con = db.connect()
    try:
        live = _live_clause(con)
        where, params = f"({live})", []
        if q and q.strip():
            like = f"%{q.strip()}%"
            where += " AND (name LIKE ? OR email_primary LIKE ? OR phone_primary LIKE ? OR company LIKE ?)"
            params.extend([like, like, like, like])
        total = con.execute(f"SELECT count(*) FROM contacts WHERE {where}", params).fetchone()[0]
        rows = con.execute(
            f"SELECT * FROM contacts WHERE {where} ORDER BY {sort} {dir.upper()}, id {dir.upper()}"
            " LIMIT ? OFFSET ?",
            params + [size, (page - 1) * size],
        ).fetchall()
        contacts = [_public(r) for r in rows]
        return {"rows": contacts, "total": total, "page": page,
                "pageSize": size,
                "totalPages": (total + size - 1) // size if total else 0}
    finally:
        con.close()


@router.get("/contacts/{contact_id}")
async def get_contact(contact_id: int):
    con = db.connect()
    try:
        live = _live_clause(con)
        row = con.execute(
            f"SELECT * FROM contacts WHERE id = ? AND {live}", (contact_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "contact not found")
        return _public(row)
    finally:
        con.close()


@router.patch("/contacts/{contact_id}")
async def update_contact(contact_id: int, body: ContactFieldsIn):
    fields = body.fields or {}
    if not isinstance(fields, dict):
        raise HTTPException(422, "fields must be an object")
    unknown = sorted(set(fields) - _EDITABLE_FIELDS)
    if unknown:
        raise HTTPException(422, f"unknown fields: {', '.join(unknown)}")
    if not fields:
        raise HTTPException(422, "no fields to update")
    con = db.connect()
    try:
        live = _live_clause(con)
        row = con.execute(
            f"SELECT id FROM contacts WHERE id = ? AND {live}", (contact_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "contact not found")
        sets, vals = [], []
        for key, val in fields.items():
            if val is not None and not isinstance(val, str):
                val = str(val)
            sets.append(f"{key} = ?")
            vals.append(val)
        contact_cols = {r[1] for r in con.execute("PRAGMA table_info(contacts)").fetchall()}
        keys = record_keys(fields)
        for source, col in (("email_primary", "email_key"), ("phone_primary", "phone_key"),
                            ("name", "name_key"), ("company", "company_key"), ("website", "website_key")):
            if source in fields and col in contact_cols:
                sets.append(f"{col} = ?")
                vals.append(keys[col])
        vals.append(contact_id)
        con.execute(f"UPDATE contacts SET {', '.join(sets)} WHERE id = ?", vals)
        con.commit()
        updated = con.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
        return {"ok": True, "contact": _public(updated)}
    except HTTPException:
        raise
    except sqlite3.Error:
        con.rollback()
        logger.exception("contacts PATCH failed for id=%s", contact_id)
        raise HTTPException(500, "could not update contact")
    finally:
        con.close()


@router.delete("/contacts/{contact_id}")
async def delete_contact(contact_id: int):
    """D-014: soft-delete (deleted_at), never a hard DELETE of the row."""
    con = db.connect()
    try:
        if not _has_deleted_at(con):
            raise HTTPException(409, "soft-delete column missing — run the migration train first")
        cur = con.execute(
            "UPDATE contacts SET deleted_at = datetime('now')"
            " WHERE id = ? AND deleted_at IS NULL",
            (contact_id,))
        if cur.rowcount == 0:
            exists = con.execute(
                "SELECT 1 FROM contacts WHERE id = ? AND deleted_at IS NULL", (contact_id,)).fetchone()
            if exists:
                raise HTTPException(409, "contact already deleted")
            raise HTTPException(404, "contact not found")
        con.commit()
        return {"ok": True, "deleted": contact_id}
    finally:
        con.close()


def _public(row: sqlite3.Row) -> dict:
    d = dict(row)
    d.pop("deleted_at", None)  # soft-delete bookkeeping is not API surface
    return d
