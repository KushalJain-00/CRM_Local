from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import json
import sqlite3
from datetime import datetime
import config as _config

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

def _get_con():
    con = sqlite3.connect(_config.db_path("crm"), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _exec(con, sql, params=()):
    """Execute SQL with error handling."""
    try:
        cur = con.execute(sql, params)
        con.commit()
        return cur
    except Exception as e:
        con.rollback()
        raise e


# ── Routes ───────────────────────────────────────────────────────────────

@router.get("/staged-contacts")
async def list_staged_contacts(
    page: int = 1,
    size: int = 20,
    review_status: Optional[str] = None,
    dedup_status: Optional[str] = None,
    import_status: Optional[str] = None,
    q: Optional[str] = None,
):
    """List staged contacts with optional filtering and pagination."""
    con = _get_con()
    try:
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
    con = _get_con()
    try:
        row = con.execute("SELECT * FROM staged_contacts WHERE id = ?", (staged_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Staged contact not found")
        return dict(row)
    finally:
        con.close()


@router.post("/staged-contacts/approve")
async def approve_staged_contact(
    body: BulkApproveRejectIn,
):
    """Approve one or more staged contacts (commit to CRM)."""
    con = _get_con()
    try:
        approved = 0
        for staged_id in body.staged_ids:
            # Validate the staged contact exists
            sc = con.execute("SELECT * FROM staged_contacts WHERE id = ?", (staged_id,)).fetchone()
            if sc is None:
                continue

            # Upsert the contact into CRM contacts table
            email = sc["email"]
            existing = con.execute(
                "SELECT id FROM contacts WHERE email_primary = ?", (email,)
            ).fetchone() if email else None

            now = datetime.utcnow().isoformat()

            if existing:
                # Update existing contact (merge - local-wins: only overwrite empty fields)
                field_map = {
                    "name": sc["name"],
                    "email_secondary": sc["email_secondary"],
                    "phone_primary": sc["phone_primary"],
                    "phone_secondary": sc["phone_secondary"],
                    "company": sc["company"],
                    "designation": sc["designation"],
                    "address": sc["address"],
                    "city": sc["city"],
                    "pincode": sc["pincode"],
                    "website": sc["website"],
                    "whatsapp": sc["whatsapp"],
                    "position": sc["position"],
                }
                update_parts = []
                update_vals = []
                col_map = {
                    "name": "name", "email_secondary": "email_secondary",
                    "phone_primary": "phone_primary", "phone_secondary": "phone_secondary",
                    "company": "company", "designation": "designation",
                    "address": "address", "city": "city", "pincode": "pincode",
                    "website": "website", "whatsapp": "whatsapp",
                    "position": "position",
                }
                for key, val in field_map.items():
                    if val is not None:
                        existing_val = con.execute(
                            f"SELECT {col_map[key]} FROM contacts WHERE id = ?",
                            (existing["id"],)
                        ).fetchone()[0]
                        if val is not None and (existing_val == "" or existing_val is None):
                            update_parts.append(f"{col_map[key]} = ?")
                            update_vals.append(val)

                if update_parts:
                    update_vals.append(existing["id"])
                    con.execute(
                        f"UPDATE contacts SET {', '.join(update_parts)} WHERE id = ?",
                        update_vals
                    )
            else:
                # Create new contact
                con.execute(
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
                        sc["position"], sc["files"], sc["email_key"], sc["phone_key"],
                        sc["name_key"], sc["company_key"], sc["website_key"],
                        sc["source_file"], sc["source_row"], sc["extraction_run_id"],
                        sc["field_origin"], now, now,
                    )
                )

            # Update review and import status
            con.execute(
                "UPDATE staged_contacts SET review_status = 'APPROVED', import_status = 'NEW_CONTACT_CREATED', reviewed_at = ? WHERE id = ?",
                (now, staged_id)
            )

            approved += 1

        con.commit()
        return {"ok": True, "approved": approved}
    finally:
        con.close()


@router.post("/staged-contacts/bulk-action")
async def bulk_staged_action(
    body: BulkApproveRejectIn,
):
    """Bulk approve or reject staged contacts."""
    return await approve_staged_contact(body)


@router.post("/staged-contacts/{staged_id}/reject")
async def reject_staged_contact(
    staged_id: int,
):
    """Reject a staged contact."""
    con = _get_con()
    try:
        now = datetime.utcnow().isoformat()
        con.execute(
            "UPDATE staged_contacts SET review_status = 'REJECTED', import_status = 'IMPORT_FAILED', "
            "validation_warnings = COALESCE(validation_warnings, '') || '; manually rejected by user', reviewed_at = ? WHERE id = ?",
            (now, staged_id)
        )
        con.commit()
        return {"ok": True, "review_status": "REJECTED"}
    finally:
        con.close()


@router.post("/staged-contacts/{staged_id}/dismiss")
async def dismiss_staged_contact(
    staged_id: int,
):
    """Dismiss a staged contact (remove from queue, keep data for audit)."""
    con = _get_con()
    try:
        now = datetime.utcnow().isoformat()
        con.execute(
            "UPDATE staged_contacts SET review_status = 'DISMISSED', import_status = 'NOT_IMPORTED', reviewed_at = ? WHERE id = ?",
            (now, staged_id)
        )
        con.commit()
        return {"ok": True, "review_status": "DISMISSED"}
    finally:
        con.close()


@router.post("/staged-contacts/{staged_id}/edit")
async def edit_staged_contact(
    staged_id: int,
    body: StagedContactIn,
):
    """Edit a staged contact's fields before approval."""
    con = _get_con()
    try:
        fields = {}
        if body.name is not None: fields["name"] = body.name
        if body.email is not None: fields["email"] = body.email
        if body.phone_primary is not None: fields["phone_primary"] = body.phone_primary
        if body.phone_secondary is not None: fields["phone_secondary"] = body.phone_secondary
        if body.company is not None: fields["company"] = body.company
        if body.designation is not None: fields["designation"] = body.designation
        if body.address is not None: fields["address"] = body.address
        if body.city is not None: fields["city"] = body.city
        if body.pincode is not None: fields["pincode"] = body.pincode
        if body.website is not None: fields["website"] = body.website
        if body.whatsapp is not None: fields["whatsapp"] = body.whatsapp
        if body.position is not None: fields["position"] = body.position
        if body.files is not None: fields["files"] = body.files
        if body.email_secondary is not None: fields["email_secondary"] = body.email_secondary
        if body.to_emails is not None: fields["to_emails"] = body.to_emails
        if body.cc_emails is not None: fields["cc_emails"] = body.cc_emails
        if body.bcc_emails is not None: fields["bcc_emails"] = body.bcc_emails

        if not fields:
            con.close()
            return {"ok": False, "error": "No fields to update"}

        set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
        vals = list(fields.values()) + [staged_id]
        con.execute(
            f"UPDATE staged_contacts SET {set_clause} WHERE id = ?",
            vals
        )
        con.commit()
        return {"ok": True}
    finally:
        con.close()


import math

@router.get("/staged-contacts/dedup-check")
async def check_staged_dedup(
    email: Optional[str] = None,
    phone: Optional[str] = None,
    name: Optional[str] = None,
):
    """Check for duplicates among staged contacts and existing CRM contacts."""
    import re
    con = _get_con()
    try:
        duplicate_reason = None

        # Normalize email
        if email:
            er = (email or "").strip().lower()
            if er:
                result = con.execute(
                    "SELECT id FROM contacts WHERE email_key = ?", (er,)
                ).fetchone()
                if result:
                    duplicate_reason = "email"

        # Normalize phone
        if phone:
            d = re.sub(r"\D", "", phone or "")
            if len(d) == 12 and d.startswith("91"):
                d = d[2:]
            if len(d) == 11 and d.startswith("0"):
                d = d[1:]
            if len(d) >= 7:
                result = con.execute(
                    "SELECT id FROM contacts WHERE phone_key = ?", (d,)
                ).fetchone()
                if result:
                    if not duplicate_reason:
                        duplicate_reason = "phone"

        # Check name + phone
        if name and phone:
            nk = (name or "").strip().lower().replace("  ", " ")
            d = re.sub(r"\D", "", phone or "")
            if len(d) == 12 and d.startswith("91"):
                d = d[2:]
            if len(d) == 11 and d.startswith("0"):
                d = d[1:]
            if len(d) >= 7:
                result = con.execute(
                    "SELECT id FROM contacts WHERE name LIKE ? AND phone_key = ?",
                    (f"%{nk}%", d)
                ).fetchone()
                if result:
                    duplicate_reason = "name + phone"

        # Check within staged contacts (email)
        if email:
            er = (email or "").strip().lower()
            if er:
                result = con.execute(
                    "SELECT COUNT(*) FROM staged_contacts WHERE email = ?", (er,)
                ).fetchone()
                if result[0] > 1:
                    if not duplicate_reason:
                        duplicate_reason = "email (within staged)"

        # Check within staged contacts (phone)
        if phone:
            d = re.sub(r"\D", "", phone or "")
            if len(d) >= 7:
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
    con = _get_con()
    try:
        # Get the staged contact
        sc = con.execute("SELECT * FROM staged_contacts WHERE id = ?", (staged_id,)).fetchone()
        if sc is None:
            con.close()
            raise HTTPException(404, "Staged contact not found")

        # Get existing contact by email
        email = sc["email"]
        existing = con.execute(
            "SELECT * FROM contacts WHERE email_primary = ?", (email,)
        ).fetchone() if email else None

        now = datetime.utcnow().isoformat()

        if existing:
            # Local-wins: only overwrite empty fields in existing
            field_map = {
                "name": sc["name"],
                "email_secondary": sc["email_secondary"],
                "phone_primary": sc["phone_primary"],
                "phone_secondary": sc["phone_secondary"],
                "company": sc["company"],
                "designation": sc["designation"],
                "address": sc["address"],
                "city": sc["city"],
                "pincode": sc["pincode"],
                "website": sc["website"],
                "whatsapp": sc["whatsapp"],
                "position": sc["position"],
            }
            update_parts = []
            update_vals = []
            col_map = {
                "name": "name", "email_secondary": "email_secondary",
                "phone_primary": "phone_primary", "phone_secondary": "phone_secondary",
                "company": "company", "designation": "designation",
                "address": "address", "city": "city", "pincode": "pincode",
                "website": "website", "whatsapp": "whatsapp",
                "position": "position",
            }
            for key, val in field_map.items():
                if val is not None:
                    existing_val = con.execute(
                        f"SELECT {col_map[key]} FROM contacts WHERE id = ?",
                        (existing["id"],)
                    ).fetchone()[0]
                    if val is not None and (existing_val == "" or existing_val is None):
                        update_parts.append(f"{col_map[key]} = ?")
                        update_vals.append(val)

            if update_parts:
                update_vals.append(existing["id"])
                con.execute(
                    f"UPDATE contacts SET {', '.join(update_parts)} WHERE id = ?",
                    update_vals
                )
            # Mark as approved even if no fields updated (existing contact enriched)
            con.execute(
                "UPDATE staged_contacts SET review_status = 'APPROVED', import_status = 'EXISTING_CONTACT_ENRICHED', reviewed_at = ? WHERE id = ?",
                (now, staged_id)
            )
        else:
            # Create new contact
            con.execute(
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
                    sc["position"], sc["files"], sc["email_key"], sc["phone_key"],
                    sc["name_key"], sc["company_key"], sc["website_key"],
                    sc["source_file"], sc["source_row"], sc["extraction_run_id"],
                    sc["field_origin"], now, now,
                )
            )
            con.execute(
                "UPDATE staged_contacts SET review_status = 'APPROVED', import_status = 'NEW_CONTACT_CREATED', reviewed_at = ? WHERE id = ?",
                (now, staged_id)
            )

        con.commit()
        con.close()
        merged = existing is not None
        return {"ok": True, "merged": merged, "new": existing is None}
    except HTTPException:
        con.close()
        raise
    except Exception as e:
        con.close()
        raise HTTPException(500, str(e))
