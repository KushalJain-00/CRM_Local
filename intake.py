# intake.py — Universal file intake for CRM_Local
import os
import re
import tempfile
import asyncio
import logging

from pathlib import Path

import config
from services.adapters import get_adapter, NormalizedContact, ExtractionResult
from services.eml_processor import parse_eml_bytes, extract_local_fields, build_llm_prompt, merge_fields
from services.eml_dedup_rules import is_duplicate, normalize_email, normalize_phone, phone_key
# `llm` must be importable as a module: line 78 calls llm.extract(...) and the
# old `from llm import parse_json as parse_llm_json` (unused) left `llm` unbound.
import llm

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_TOTAL_SIZE = 100 * 1024 * 1024
MAX_FILE_COUNT = 50
SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".pdf", ".txt", ".eml"}

_MAGIC = {
    "xls": [b"\xd0\xcf\x11\xe0", b"\x09\x08\x08\x00"],
    "pdf": [b"%PDF"],
}


async def universal_intake(files, chain=None, options=None):
    """Process a batch of mixed-format files through the unified extraction pipeline."""
    chain = chain or []
    options = options or {}
    results = []
    counts = {"new": 0, "duplicate": 0, "merged": 0, "error": 0, "skipped": 0}
    total_size = 0

    import db
    from services import staging
    con = db.connect("crm")
    # Resolve data directory for bare filename resolution
    data_dir = Path(config.data_dir()).resolve()
    total_contacts = 0
    run_id = None
    try:
        run_id = staging.open_extraction_run(con, files_processed=len(files))
        for uf_path in files:
            # Spool files arrive as "<pid>~<i>~<original>" — show the original.
            name = re.sub(r"^\d+~\d+~", "", os.path.basename(uf_path))
            ext = os.path.splitext(name)[1].lower()
            try:
                # If the path has no directory component (bare filename), treat
                # it as relative to the data directory. This handles the case where
                # a client sends only a filename (e.g. from a dropzone without
                # full path information).
                has_dir = os.path.sep in uf_path or (os.path.altsep and os.path.altsep in uf_path)
                if not has_dir:
                    uf_path = str(data_dir / uf_path)
                if not os.path.exists(uf_path):
                    raise ValueError(f"file not found: {name}")
                size = os.path.getsize(uf_path)
                if size > MAX_FILE_SIZE:
                    raise ValueError(f"file too large (max {MAX_FILE_SIZE // (1024*1024)}MB)")
                total_size += size
                if total_size > MAX_TOTAL_SIZE:
                    raise ValueError(f"total upload size exceeds {MAX_TOTAL_SIZE // (1024*1024)}MB")
                if ext not in SUPPORTED_EXTENSIONS:
                    raise ValueError(f"unsupported file type: {ext}")

                with open(uf_path, "rb") as f:
                    raw = f.read()

                # Magic bytes validation
                if ext in (".xls", ".pdf"):
                    magic_ext = ext.lstrip(".")
                    if magic_ext in _MAGIC:
                        if not any(raw[:len(m)] == m for m in _MAGIC[magic_ext]):
                            raise ValueError(f"file content does not match {ext} format")

                adapter = get_adapter(uf_path)
                if adapter is None:
                    raise ValueError(f"no adapter for {ext}")

                result = await adapter.extract(uf_path)

                # For EML files, persist the email row and stage a linked
                # contact (D-006/D-007: never canonical from intake).
                source_email_id = None
                raw_eml = raw if ext == ".eml" else None
                if ext == ".eml":
                    from services.eml_processor import parse_eml_bytes
                    parsed = parse_eml_bytes(raw, name)
                    source_email_id = db.insert_email(con, parsed, name)

                if chain:
                    import config as _config
                    import parse as _parse
                    from services.prompts import store as _prompts
                    from services.ai_assist import assist_document
                    _cfg = _config.load()
                    if ext == ".eml":
                        from services.eml_processor import build_llm_prompt, merge_fields, extract_local_fields
                        ai, label = await llm.extract(
                            chain, build_llm_prompt(parsed),
                            system=_prompts.text("eml"),
                            reliability=_cfg.get("reliability"))
                        if ai:
                            local = extract_local_fields(parsed)
                            merged = merge_fields(local, ai)
                            for nc in result.contacts:
                                nc.name = merged.get("name") or nc.name
                                nc.email_primary = merged.get("email") or nc.email_primary
                                nc.phone_primary = merged.get("phone_primary") or nc.phone_primary
                                nc.company = merged.get("company") or nc.company
                                nc.designation = merged.get("designation") or nc.designation
                                nc.address = merged.get("address") or nc.address
                                nc.city = merged.get("city") or nc.city
                                nc.pincode = merged.get("pincode") or nc.pincode
                                nc.website = merged.get("website") or nc.website
                                nc.field_origin = {k: ("ai" if (ai and ai.get(k)) else "local") for k in ["name", "email", "phone_primary", "company", "designation", "address", "city", "pincode", "website"] if merged.get(k)}
                    elif ext in (".csv", ".xlsx", ".xls", ".pdf"):
                        try:
                            table = _parse.read_table(uf_path)
                        except Exception:
                            table = None
                        if table:
                            ai_contacts = await assist_document(
                                table, name=name, chain=chain, cfg=_cfg,
                                source_type="spreadsheet")
                            if ai_contacts:
                                from services.adapters import NormalizedContact
                                for ac in ai_contacts:
                                    result.contacts.append(NormalizedContact(
                                        name=ac.get("name"),
                                        email_primary=ac.get("email_primary"),
                                        email_secondary=ac.get("email_secondary"),
                                        phone_primary=ac.get("phone_primary"),
                                        phone_secondary=ac.get("phone_secondary"),
                                        whatsapp=ac.get("whatsapp"),
                                        company=ac.get("company"),
                                        designation=ac.get("designation"),
                                        address=ac.get("address"),
                                        city=ac.get("city"),
                                        pincode=ac.get("pincode"),
                                        website=ac.get("website"),
                                        source_file=name,
                                        field_origin=ac.get("field_origin"),
                                        confidence=ac.get("confidence") or 0.3,
                                    ))

                # Stage contacts — canonical writes happen only at approval.
                # IMPORTANT: staged_contacts may not exist yet on an unmigrated
                # live DB; that surfaces as an explicit error, never silent loss.
                staged = staging.stage_contacts(
                    con, [vars(nc) for nc in result.contacts],
                    source_type=ext.lstrip("."),
                    source_file=name,
                    source_email_id=source_email_id,
                    extraction_run_id=run_id,
                )
                if source_email_id is not None:
                    # link staged rows created for this email (M:N)
                    ids = [r[0] for r in con.execute(
                        "SELECT id FROM staged_contacts WHERE source_email_id = ?",
                        (source_email_id,)).fetchall()]
                    for sid in ids:
                        con.execute(
                            "INSERT OR IGNORE INTO email_staged_links (email_id, staged_contact_id, created_at)"
                            " VALUES (?, ?, ?)",
                            (source_email_id, sid, db.now_iso()))
                total_contacts += staged["staged"]
                counts["new"] += staged["staged"]
                counts["skipped"] += staged["needs_review"]

                db.mark_processed(con, name, size, os.path.getmtime(uf_path), "ok",
                                  None, contacts_found=len(result.contacts))
                results.append({
                    "file": name,
                    "status": "OK",
                    "contacts_found": len(result.contacts),
                    "warnings": result.warnings,
                    "adapter": result.adapter,
                })
            except Exception as exc:
                counts["error"] += 1
                results.append({"file": name, "status": "ERROR", "error": str(exc)})
                try:
                    db.mark_processed(con, name, os.path.getsize(uf_path) if os.path.exists(uf_path) else 0,
                                      os.path.getmtime(uf_path) if os.path.exists(uf_path) else 0,
                                      "error", str(exc)[:300])
                except Exception:
                    pass

        if run_id is not None:
            staging.close_extraction_run(con, run_id, total_contacts,
                                         status="completed" if counts["error"] == 0 else "completed_with_errors")
        con.commit()
    finally:
        con.close()

    # Top-level ok means "request handled"; per-file failures are reported in
    # results[].status == "ERROR" (frontend contract — see tests/test_intake.py).
    return {"ok": True, "results": results, "counts": counts}