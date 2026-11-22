"""Canonical writes for manual and policy-driven staging approval."""
import db
from services.keys import normalize_email, phone_key, record_keys


_CONTACT_FIELD_MAP = {
    "name": "name", "email_secondary": "email_secondary",
    "phone_primary": "phone_primary", "phone_secondary": "phone_secondary",
    "company": "company", "designation": "designation",
    "address": "address", "city": "city", "pincode": "pincode",
    "website": "website", "whatsapp": "whatsapp",
    "position": "position", "source_file": "source_file",
}

def _canon_keys(sc) -> dict:
    """Dedup keys for a new canonical contact, always from the authoritative
    normalizers — identical to what staged rows were written with."""
    return record_keys(dict(sc))

def _secondary_phone(value):
    return value.split(",", 1)[0].strip() if value else None


def _enrich_existing(con, existing_id: int, sc) -> None:
    """Local-wins merge: only fill fields that are empty in the canonical row.

    Key-bearing columns are recomputed after filling so canonical rows never
    carry NULL keys for populated values."""
    for staged_col, canon_col in _CONTACT_FIELD_MAP.items():
        val = sc[staged_col] if staged_col in sc.keys() else None
        if staged_col == "phone_secondary":
            val = _secondary_phone(val)
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
    live = "deleted_at IS NULL" if "deleted_at" in db._table_cols(con, "contacts") else "1=1"
    existing = None
    e = normalize_email(email)
    if e:
        existing = con.execute(
            f"SELECT id FROM contacts WHERE {live} AND lower(trim(email_primary)) = ?"
            " ORDER BY id LIMIT 1", (e,)).fetchone()
    if existing is None:
        pk = phone_key(phone)
        if pk:
            existing = con.execute(
                f"SELECT id FROM contacts WHERE {live} AND phone_key = ? ORDER BY id LIMIT 1",
                (pk,)).fetchone()
    return existing


def _insert_contact(con, sc) -> int:
    keys = _canon_keys(sc)
    now = db.now_iso()
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
            _secondary_phone(sc["phone_secondary"]), sc["company"], sc["designation"], sc["address"],
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

def approve_ids(con, staged_ids: list[int]) -> dict:
    """Approve staged rows into canonical contacts. Returns per-row outcomes."""
    approved = already = failed = 0
    for staged_id in staged_ids:
        sc = con.execute("SELECT * FROM staged_contacts WHERE id = ?", (staged_id,)).fetchone()
        if sc is None or sc["review_status"] in ("REJECTED", "DISMISSED"):
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

        now = db.now_iso()
        con.execute(
            "UPDATE staged_contacts SET review_status = 'APPROVED', import_status = ?,"
            " crm_contact_id = ?, pushed_to_crm = 1, reviewed_at = ?, updated_at = ? WHERE id = ?",
            (import_status, contact_id, now, now, staged_id))
        approved += 1
    return {"approved": approved, "already_approved": already, "failed": failed}
