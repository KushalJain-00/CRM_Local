# services/staging.py — the ONLY write path for extracted contacts.
# Extracted records are staged for human review (D-006/D-007); canonical
# contacts are created/enriched exclusively by the approval flow.
import json
from datetime import datetime, timezone

from services import validation, dedup
from services.keys import record_keys, identity_key


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dedup_vs_canonical(con, d: dict) -> tuple[str, list[int]]:
    """Band the staged record against canonical contacts. Human decides; we report."""
    keys = record_keys(d)
    cands: list[int] = []
    try:
        if keys["email_key"]:
            cands += [r[0] for r in con.execute(
                "SELECT id FROM contacts WHERE email_key = ? AND deleted_at IS NULL",
                (keys["email_key"],)).fetchall()]
        if keys["phone_key"]:
            cands += [r[0] for r in con.execute(
                "SELECT id FROM contacts WHERE phone_key = ? AND deleted_at IS NULL",
                (keys["phone_key"],)).fetchall()]
        if keys["name_key"] and keys["company_key"]:
            cands += [r[0] for r in con.execute(
                "SELECT id FROM contacts WHERE name_key = ? AND company_key = ? AND deleted_at IS NULL",
                (keys["name_key"], keys["company_key"])).fetchall()]
    except Exception:
        # deleted_at missing pre-v6 — fall back to plain key match
        if keys["email_key"]:
            cands += [r[0] for r in con.execute(
                "SELECT id FROM contacts WHERE email_key = ?", (keys["email_key"],)).fetchall()]
        if keys["phone_key"]:
            cands += [r[0] for r in con.execute(
                "SELECT id FROM contacts WHERE phone_key = ?", (keys["phone_key"],)).fetchall()]
    cands = list(dict.fromkeys(cands))
    if not cands:
        return dedup.UNIQUE, []
    band = dedup.UNIQUE
    for cid in cands[:5]:
        row = con.execute("SELECT * FROM contacts WHERE id = ?", (cid,)).fetchone()
        if row is None:
            continue
        existing = dict(row)
        res = dedup.compare(d, existing)
        order = [dedup.UNIQUE, dedup.PROBABLE_DUPLICATE, dedup.CONFLICT, dedup.EXACT_DUPLICATE]
        if order.index(res["band"]) > order.index(band):
            band = res["band"]
    return band, cands


def stage_contacts(con, contacts: list[dict], *, source_type: str, source_file: str,
                   source_email_id: int | None = None, source_row: int | None = None,
                   extraction_run_id: int | None = None,
                   raw_source_data=None) -> dict:
    """Insert staged_contacts rows for extracted contacts. Returns per-file counts.

    Never writes canonical tables. Missing identity (no email AND no phone)
    is staged as NEEDS_REVIEW with the MISSING warning preserved, never dropped.
    """
    counts = {"staged": 0, "needs_review": 0, "duplicates": 0, "invalid": 0,
              "batch_duplicates": 0}
    seen_keys: set[tuple] = set()
    run_raw = json.dumps(raw_source_data, default=str) if raw_source_data is not None else None
    for nc in contacts:
        d = dict(nc)
        d.setdefault("email_primary", d.get("email"))
        keys = record_keys(d)
        batch_key = identity_key(d)
        if batch_key != ("n", None, None):
            if batch_key in seen_keys:
                counts["batch_duplicates"] += 1
                continue
            seen_keys.add(batch_key)
        issues = validation.validate_record({
            "name": d.get("name"), "email_primary": d.get("email_primary"),
            "email_secondary": d.get("email_secondary"),
            "phone_primary": d.get("phone_primary"),
            "phone_secondary": d.get("phone_secondary"),
            "whatsapp": d.get("whatsapp"), "pincode": d.get("pincode"),
            "company": d.get("company"), "position": d.get("position"),
            "designation": d.get("designation"), "address": d.get("address"),
            "city": d.get("city"), "website": d.get("website"),
        })
        errors = [i for i in issues if i.get("severity") == "error"]
        warnings = [f"{i['field']}: {i['message']}" for i in issues]
        band, candidates = _dedup_vs_canonical(con, d)
        validation_status = "INVALID" if errors else "VALID"
        if errors:
            counts["invalid"] += 1
        if band != dedup.UNIQUE:
            counts["duplicates"] += 1
        needs_review = bool(errors) or band in (dedup.EXACT_DUPLICATE,
                                                dedup.PROBABLE_DUPLICATE,
                                                dedup.CONFLICT)
        review_status = "NEEDS_REVIEW" if needs_review else "READY"
        if needs_review:
            counts["needs_review"] += 1
        evidence = {"source_file": source_file}
        if d.get("source_row") is not None:
            evidence["row"] = d["source_row"]
        if d.get("field_origin"):
            evidence["field_origin"] = d["field_origin"]
        con.execute(
            """INSERT INTO staged_contacts (
                source_type, source_file, source_row, source_sheet, source_email_id,
                name, email, email_secondary, phone_primary, phone_secondary,
                company, designation, address, city, pincode, website, whatsapp,
                position, files, products_misc,
                to_emails, cc_emails, bcc_emails,
                email_key, phone_key, name_key, company_key, website_key,
                raw_source_data, field_evidence, confidence, extraction_run_id,
                validation_status, validation_warnings, review_status,
                dedup_status, duplicate_candidate_ids,
                import_status, pushed_to_crm, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source_type, source_file,
                d.get("source_row", source_row), d.get("source_sheet"), source_email_id,
                d.get("name"), d.get("email_primary") or d.get("email"),
                d.get("email_secondary"), d.get("phone_primary"), d.get("phone_secondary"),
                d.get("company"), d.get("designation"), d.get("address"), d.get("city"),
                d.get("pincode"), d.get("website"), d.get("whatsapp"),
                d.get("position"), d.get("files"), d.get("products_misc"),
                d.get("to_emails"), d.get("cc_emails"), d.get("bcc_emails"),
                keys["email_key"], keys["phone_key"], keys["name_key"],
                keys["company_key"], keys["website_key"],
                run_raw or json.dumps(d, default=str),
                json.dumps(evidence), float(d.get("confidence") or 0.0),
                extraction_run_id, validation_status,
                json.dumps(warnings) if warnings else None, review_status,
                band, json.dumps(candidates) if candidates else None,
                "NOT_IMPORTED", 0, _now(), _now(),
            ))
        counts["staged"] += 1
    return counts


def open_extraction_run(con, files_processed: int = 0, config_snapshot=None) -> int:
    cur = con.execute(
        "INSERT INTO extraction_runs (started_at, status, files_processed, config_snapshot)"
        " VALUES (?, 'running', ?, ?)",
        (_now(), files_processed,
         json.dumps(config_snapshot, default=str) if config_snapshot else None),
    )
    return cur.lastrowid


def close_extraction_run(con, run_id: int, contacts_found: int, status: str = "completed",
                         error: str | None = None) -> None:
    con.execute(
        "UPDATE extraction_runs SET completed_at = ?, status = ?, contacts_found = ?, error = ?"
        " WHERE id = ?",
        (_now(), status, contacts_found, error, run_id),
    )
