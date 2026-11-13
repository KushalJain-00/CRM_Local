from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query

import logging
import math
from datetime import datetime
import db
from services.keys import normalize_email, phone_key, normalize_name, record_keys

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Schemas ──────────────────────────────────────────────────────────────

class StagedContactIn(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone_primary: Optional[str] = None
    phone_secondary: Optional[str] = None
    company: Optional[str] = None
    designation: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    website: Optional[str] = None
    whatsapp: Optional[str] = None
    position: Optional[str] = None
    files: Optional[str] = None
    email_secondary: Optional[str] = None
    to_emails: Optional[str] = None
    cc_emails: Optional[str] = None
    bcc_emails: Optional[str] = None

class BulkApproveRejectIn(BaseModel):
    staged_ids: List[int]
    action: str  # "approve" or "reject"

# ── DB helper ─────────────────────────────────────────────────────────────

def _exec(con, sql, params=()):
    """Execute SQL with error handling."""
    try:
        cur = con.execute(sql, params)
        con.commit()
        return cur
    except Exception as e:
        con.rollback()
        raise e

def _require_staged_table(con):
    """Live DB is at migration v1 by standing user decision (2026-11-07 board note —
    the v2+ train is gated on an explicit go-ahead). Absent table = actionable 503,
    never a bare 500 and never a fake empty payload."""
    if not con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='staged_contacts'"
    ).fetchone():
        raise HTTPException(
            503,
            "staged_contacts table is not provisioned yet — the staging schema is applied "
            "by the gated migration train (CRM_APPLY_MIGRATIONS=1), which is pending "
            "explicit approval. See docs/INTERFACE_CONTRACTS.md / DECISIONS.md D-030.",
        )

# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/staged-contacts")
async def list_staged_contacts(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    review_status: Optional[str] = None,
    dedup_status: Optional[str] = None,
    import_status: Optional[str] = None,
    q: Optional[str] = None,
):
    """List staged contacts with optional filtering and pagination."""
    con = db.connect()
    try:
        _require_staged_table(con)
        # Build WHERE clause
        where = "1=1"
        params = []

        if review_status:
            where += " AND review_status = ?"
            params.append(review_status)
        if dedup_status:
            where += " AND dedup_status = ?"
            params.append(dedup_status)
        if import_status:
            where += " AND import_status = ?"
            params.append(import_status)
        if q:
            where += " AND (name LIKE ? OR email LIKE ? OR phone_primary LIKE ? OR company LIKE ?)"
            like = f"%{q}%"
            params.extend([like, like, like, like])

        # Count total
        count_sql = f"SELECT COUNT(*) FROM staged_contacts WHERE {where}"
        total = con.execute(count_sql, params).fetchone()[0]

        # Pagination
        offset = (page - 1) * size
        list_sql = f"""
            SELECT * FROM staged_contacts WHERE {where}
            ORDER BY created_at DESC LIMIT ? OFFSET ?
        """
        list_params = params + [size, offset]
        rows = con.execute(list_sql, list_params).fetchall()

        contacts = [dict(r) for r in rows]
        return {
            "rows": contacts,
            "total": total,
            "page": page,
            "pageSize": size,
            "totalPages": math.ceil(total / size) if total > 0 else 0,
        }
    finally:
        con.close()

@router.get("/staged-contacts/{staged_id}")
async def get_staged_contact(staged_id: int):
    """Get a single staged contact by ID."""
    con = db.connect()
    try:
        _require_staged_table(con)
        row = con.execute("SELECT * FROM staged_contacts WHERE id = ?", (staged_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Staged contact not found")
        return dict(row)
    finally:
        con.close()

# ── Approval core (shared by per-id, bulk and bulk-action endpoints) ────────

_CONTACT_FIELD_MAP = {
    "name": "name", "email_secondary": "email_secondary",
    "phone_primary": "phone_primary", "phone_secondary": "phone_secondary",
    "company": "company", "designation": "designation",
    "address": "address", "city": "city", "pincode": "pincode",
    "website": "website", "whatsapp": "whatsapp",
    "position": "position",
}

def _canon_keys(sc) -> dict:
    """Dedup keys for a new canonical contact, always from the authoritative
    normalizers — identical to what staged rows were written with."""
    return record_keys(dict(sc))

# staged/canonical column → its dedup-key column
_KEY_BY_FIELD = {"name": "name_key", "phone_primary": "phone_key",
                 "company": "company_key", "website": "website_key"}


def _enrich_existing(con, existing_id: int, sc) -> None:
    """Local-wins merge: only fill fields that are empty in the canonical row.

    Key-bearing columns are recomputed after filling so canonical rows never
    carry NULL keys for populated values."""
    for staged_col, canon_col in _CONTACT_FIELD_MAP.items():
        val = sc[staged_col] if staged_col in sc.keys() else None
        if val is None:
            continue
        existing_val = con.execute(
            f"SELECT {canon_col} FROM contacts WHERE id = ?", (existing_id,)).fetchone()[0]
        if existing_val == "" or existing_val is None:
            con.execute(f"UPDATE contacts SET {canon_col} = ? WHERE id = ?", (val, existing_id))
    # Self-heal: canonical rows never carry NULL keys for populated values.
    row = con.execute(
        "SELECT name, phone_primary, company, website FROM contacts WHERE id = ?",
        (existing_id,)).fetchone()
    keys = record_keys({"name": row[0], "phone_primary": row[1],
                        "company": row[2], "website": row[3]})
    con.execute(
        "UPDATE contacts SET name_key = ?, phone_key = ?, company_key = ?, website_key = ?"
        " WHERE id = ?",
        (keys["name_key"], keys["phone_key"], keys["company_key"], keys["website_key"],
         existing_id))

def _find_contact_by_identity(con, email, phone):
    """Shared identity lookup for approval/merge. Email matches
    case/space-insensitively (legacy rows may predate email_key); phone matches
    through the authoritative key."""
    existing = None
    e = normalize_email(email)
    if e:
        existing = con.execute(
            "SELECT id FROM contacts WHERE email_primary IS NOT NULL AND lower(email_primary) = ?"
            " ORDER BY id LIMIT 1", (e,)).fetchone()
    if existing is None:
        pk = phone_key(phone)
        if pk:
            existing = con.execute(
                "SELECT id FROM contacts WHERE phone_key = ? ORDER BY id LIMIT 1",
                (pk,)).fetchone()
    return existing


def _insert_contact(con, sc) -> int:
    keys = _canon_keys(sc)
    now = datetime.utcnow().isoformat()
    cur = con.execute(
        """INSERT INTO contacts (
            name, email_primary, email_secondary, phone_primary, phone_secondary,
            company, designation, address, city, pincode, website, whatsapp,
            position, files, email_key, phone_key, name_key, company_key,
            website_key, source_file, source_row, extraction_run_id, field_origin,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            sc["name"], sc["email"], sc["email_secondary"], sc["phone_primary"],
            sc["phone_secondary"], sc["company"], sc["designation"], sc["address"],
            sc["city"], sc["pincode"], sc["website"], sc["whatsapp"],
            sc["position"], sc["files"], keys["email_key"], keys["phone_key"],
            keys["name_key"], keys["company_key"], keys["website_key"],
            sc["source_file"], sc["source_row"], sc["extraction_run_id"],
            # contacts.field_origin ← staged.field_evidence: the v4 backfill copies
            # eml_contacts.field_origin (per-field "ai"/"local" JSON) into field_evidence;
            # for native-staged rows this carries whatever provenance the adapter had.
            sc["field_evidence"], now, now,
        ),
    )
    return int(cur.lastrowid)

def _approve_ids(con, staged_ids: List[int]) -> dict:
    """Approve staged rows into canonical contacts. Returns per-row outcomes."""
    approved = already = failed = 0
    for staged_id in staged_ids:
        sc = con.execute("SELECT * FROM staged_contacts WHERE id = ?", (staged_id,)).fetchone()
        if sc is None:
            failed += 1
            continue
        if sc["review_status"] == "APPROVED":
            already += 1  # replay-safe: never double-commit
            continue
        existing = _find_contact_by_identity(con, sc["email"], sc["phone_primary"])

        if existing:
            _enrich_existing(con, existing["id"], sc)
            contact_id = existing["id"]
            import_status = "EXISTING_CONTACT_ENRICHED"
        else:
            contact_id = _insert_contact(con, sc)
            import_status = "NEW_CONTACT_CREATED"

        now = datetime.utcnow().isoformat()
        con.execute(
            "UPDATE staged_contacts SET review_status = 'APPROVED', import_status = ?,"
            " crm_contact_id = ?, pushed_to_crm = 1, reviewed_at = ?, updated_at = ? WHERE id = ?",
            (import_status, contact_id, now, now, staged_id))
        approved += 1
    return {"approved": approved, "already_approved": already, "failed": failed}

def _approve_ids_logged(staged_ids: List[int]) -> dict:
    con = db.connect()
    try:
        _require_staged_table(con)
        outcome = _approve_ids(con, staged_ids)
        con.commit()
        return outcome
    except HTTPException:
        con.rollback()
        raise
    except Exception:
        con.rollback()
        logger.exception("staged approval failed for ids=%s", staged_ids)
        raise HTTPException(500, "could not approve staged contact(s)")
    finally:
        con.close()

@router.post("/staged-contacts/approve")
async def approve_staged_contact(
    body: BulkApproveRejectIn,
):
    """Approve one or more staged contacts (commit to CRM)."""
    if body.action not in ("approve",):
        raise HTTPException(422, "action must be 'approve'")
    outcome = _approve_ids_logged(body.staged_ids)
    return {"ok": True, **outcome}

@router.post("/staged-contacts/bulk-action")
async def bulk_staged_action(
    body: BulkApproveRejectIn,
):
    """Bulk approve or reject staged contacts."""
    if body.action == "approve":
        outcome = _approve_ids_logged(body.staged_ids)
        return {"ok": True, **outcome}
    if body.action in ("reject", "dismiss"):
        con = db.connect()
        try:
            _require_staged_table(con)
            now = datetime.utcnow().isoformat()
            for staged_id in body.staged_ids:
                status = "REJECTED" if body.action == "reject" else "DISMISSED"
                import_status = "IMPORT_FAILED" if body.action == "reject" else "NOT_IMPORTED"
                con.execute(
                    "UPDATE staged_contacts SET review_status = ?, import_status = ?, reviewed_at = ?"
                    " WHERE id = ? AND review_status NOT IN ('APPROVED','REJECTED','DISMISSED')",
                    (status, import_status, now, staged_id))
            con.commit()
            return {"ok": True, "action": body.action}
        except HTTPException:
            con.rollback()
            raise
        except Exception:
            con.rollback()
            logger.exception("bulk %s failed for ids=%s", body.action, body.staged_ids)
            raise HTTPException(500, f"could not {body.action} staged contact(s)")
        finally:
            con.close()
    raise HTTPException(422, "action must be 'approve', 'reject' or 'dismiss'")

@router.post("/staged-contacts/{staged_id}/approve")
async def approve_one_staged_contact(staged_id: int):
    """Single-id approve used by the review UI (same core as the bulk endpoint)."""
    outcome = _approve_ids_logged([staged_id])
    if outcome["approved"] == 0 and outcome["already_approved"] == 0:
        raise HTTPException(404, "staged contact not found")
    return {"ok": True, **outcome}

def _decide_one(con, staged_id: int, review_status: str, import_status: str) -> bool:
    """Apply a terminal review decision; returns False when the row is missing."""
    now = datetime.utcnow().isoformat()
    if review_status == "REJECTED":
        cur = con.execute(
            "UPDATE staged_contacts SET review_status = 'REJECTED', import_status = 'IMPORT_FAILED',"
            " validation_warnings = COALESCE(validation_warnings, '') || '; manually rejected by user',"
            " reviewed_at = ?, updated_at = ? WHERE id = ? AND review_status <> 'APPROVED'",
            (now, now, staged_id))
    elif review_status == "DISMISSED":
        cur = con.execute(
            "UPDATE staged_contacts SET review_status = 'DISMISSED', import_status = 'NOT_IMPORTED',"
            " reviewed_at = ?, updated_at = ? WHERE id = ? AND review_status <> 'APPROVED'",
            (now, now, staged_id))
    else:
        raise AssertionError(f"unhandled decision {review_status}")
    return cur.rowcount > 0

@router.post("/staged-contacts/{staged_id}/reject")
async def reject_staged_contact(
    staged_id: int,
):
    """Reject a staged contact (canonical CRM stays untouched)."""
    con = db.connect()
    try:
        _require_staged_table(con)
        if not _decide_one(con, staged_id, "REJECTED", "IMPORT_FAILED"):
            exists = con.execute(
                "SELECT 1 FROM staged_contacts WHERE id = ?", (staged_id,)).fetchone()
            con.close()
            if exists:
                raise HTTPException(409, "cannot reject an already-approved staged contact")
            raise HTTPException(404, "Staged contact not found")
        con.commit()
        return {"ok": True, "review_status": "REJECTED"}
    finally:
        con.close()

@router.post("/staged-contacts/{staged_id}/dismiss")
async def dismiss_staged_contact(
    staged_id: int,
):
    """Dismiss a staged contact (remove from queue, keep data for audit)."""
    con = db.connect()
    try:
        _require_staged_table(con)
        if not _decide_one(con, staged_id, "DISMISSED", "NOT_IMPORTED"):
            exists = con.execute(
                "SELECT 1 FROM staged_contacts WHERE id = ?", (staged_id,)).fetchone()
            con.close()
            if exists:
                raise HTTPException(409, "cannot dismiss an already-approved staged contact")
            raise HTTPException(404, "Staged contact not found")
        con.commit()
        return {"ok": True, "review_status": "DISMISSED"}
    finally:
        con.close()

_STAGED_EDITABLE = {
    "name", "email", "phone_primary", "phone_secondary", "company",
    "designation", "address", "city", "pincode", "website", "whatsapp",
    "position", "files", "email_secondary", "to_emails", "cc_emails", "bcc_emails",
}

class StagedFieldsIn(BaseModel):
    fields: Dict[str, Any]

def _apply_field_edits(con, staged_id: int, fields: dict) -> bool:
    unknown = sorted(set(fields) - _STAGED_EDITABLE)
    if unknown:
        raise HTTPException(422, f"unknown fields: {', '.join(unknown)}")
    if not fields:
        return False
    fields = {k: v for k, v in fields.items() if v is not None}
    if not fields:
        return False
    _STAGED_KEY = {"name": "name_key", "email": "email_key",
                   "phone_primary": "phone_key", "company": "company_key",
                   "website": "website_key"}
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [staged_id]
    cur = con.execute(
        f"UPDATE staged_contacts SET {set_clause}, updated_at = datetime('now') WHERE id = ?", vals)
    key_fields = {k for k in fields if k in _STAGED_KEY}
    if key_fields:
        row = con.execute(
            "SELECT name, email, phone_primary, company, website FROM staged_contacts WHERE id = ?",
            (staged_id,)).fetchone()
        keys = record_keys({"name": row[0], "email": row[1], "email_primary": row[1],
                            "phone_primary": row[2], "company": row[3], "website": row[4]})
        for k in key_fields:
            con.execute(f"UPDATE staged_contacts SET {_STAGED_KEY[k]} = ? WHERE id = ?",
                        (keys[_STAGED_KEY[k]], staged_id))
    return cur.rowcount > 0

@router.patch("/staged-contacts/{staged_id}")
async def patch_staged_contact(
    staged_id: int,
    body: StagedFieldsIn,
):
    """Patch a staged contact's fields before approval (frontend edit drawer)."""
    con = db.connect()
    try:
        _require_staged_table(con)
        exists = con.execute(
            "SELECT 1 FROM staged_contacts WHERE id = ?", (staged_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "Staged contact not found")
        if not _apply_field_edits(con, staged_id, body.fields or {}):
            raise HTTPException(422, "no fields to update")
        con.commit()
        return {"ok": True}
    except HTTPException:
        con.close()
        raise
    except Exception:
        con.rollback()
        con.close()
        logger.exception("PATCH staged-contacts/%s failed", staged_id)
        raise HTTPException(500, "could not update staged contact")

@router.post("/staged-contacts/{staged_id}/edit")
async def edit_staged_contact(
    staged_id: int,
    body: StagedContactIn,
):
    """Edit a staged contact's fields before approval."""
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    con = db.connect()
    try:
        _require_staged_table(con)
        exists = con.execute(
            "SELECT 1 FROM staged_contacts WHERE id = ?", (staged_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "Staged contact not found")
        if not _apply_field_edits(con, staged_id, fields):
            return {"ok": False, "error": "No fields to update"}
        con.commit()
        return {"ok": True}
    finally:
        con.close()

@router.get("/staged-contacts/dedup-check")
async def check_staged_dedup(
    email: Optional[str] = None,
    phone: Optional[str] = None,
    name: Optional[str] = None,
):
    """Check for duplicates among staged contacts and existing CRM contacts."""
    con = db.connect()
    try:
        _require_staged_table(con)
        duplicate_reason = None

        # Normalize email
        if email:
            er = normalize_email(email)
            if er:
                result = con.execute(
                    "SELECT id FROM contacts WHERE email_key = ?", (er,)
                ).fetchone()
                if result:
                    duplicate_reason = "email"

        # Normalize phone
        if phone:
            d = phone_key(phone)
            if d:
                result = con.execute(
                    "SELECT id FROM contacts WHERE phone_key = ?", (d,)
                ).fetchone()
                if result:
                    if not duplicate_reason:
                        duplicate_reason = "phone"

        # Check name + phone
        if name and phone:
            nk = normalize_name(name)
            d = phone_key(phone)
            if d:
                result = con.execute(
                    "SELECT id FROM contacts WHERE name LIKE ? AND phone_key = ?",
                    (f"%{nk}%", d)
                ).fetchone()
                if result:
                    duplicate_reason = "name + phone"

        # Check within staged contacts (email)
        if email:
            er = normalize_email(email)
            if er:
                result = con.execute(
                    "SELECT COUNT(*) FROM staged_contacts WHERE email = ?", (er,)
                ).fetchone()
                if result[0] > 1:
                    if not duplicate_reason:
                        duplicate_reason = "email (within staged)"

        # Check within staged contacts (phone)
        if phone:
            d = phone_key(phone)
            if d:
                result = con.execute(
                    "SELECT COUNT(*) FROM staged_contacts WHERE phone_primary LIKE ?",
                    (f"%{d}%",)
                ).fetchone()
                if result[0] > 1 and not duplicate_reason:
                    duplicate_reason = "phone (within staged)"

        return {
            "is_duplicate": duplicate_reason is not None,
            "duplicate_reason": duplicate_reason,
        }
    finally:
        con.close()

@router.post("/staged-contacts/{staged_id}/merge")
async def merge_staged_contact(
    staged_id: int,
):
    """Merge a staged contact with existing CRM contact (local-wins semantics)."""
    con = db.connect()
    try:
        _require_staged_table(con)
        sc = con.execute("SELECT * FROM staged_contacts WHERE id = ?", (staged_id,)).fetchone()
        if sc is None:
            raise HTTPException(404, "Staged contact not found")

        existing = _find_contact_by_identity(con, sc["email"], sc["phone_primary"])
        now = datetime.utcnow().isoformat()

        if existing:
            _enrich_existing(con, existing["id"], sc)
            contact_id = existing["id"]
            import_status = "EXISTING_CONTACT_ENRICHED"
        else:
            contact_id = _insert_contact(con, sc)
            import_status = "NEW_CONTACT_CREATED"

        con.execute(
            "UPDATE staged_contacts SET review_status = 'APPROVED', import_status = ?,"
            " crm_contact_id = ?, pushed_to_crm = 1, reviewed_at = ?, updated_at = ? WHERE id = ?",
            (import_status, contact_id, now, now, staged_id))
        con.commit()
        con.close()
        return {"ok": True, "merged": existing is not None, "new": existing is None}
    except HTTPException:
        con.close()
        raise
    except Exception:
        con.rollback()
        con.close()
        logger.exception("merge failed for staged id=%s", staged_id)
        raise HTTPException(500, "could not merge staged contact")
