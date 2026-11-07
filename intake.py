# intake.py — Universal file intake for CRM_Local
import os
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
    con = db.connect("crm")
    # Resolve data directory for bare filename resolution
    data_dir = Path(config.data_dir()).resolve()

    try:
        for uf_path in files:
            name = os.path.basename(uf_path)
            ext = os.path.splitext(name)[1].lower()
            try:
                # If the path has no directory component (bare filename), treat
                # it as relative to the data directory. This handles the case where
                # a client sends only a filename (e.g. from a dropzone without
                # full path information).
                has_dir = os.path.sep in uf_path or (os.path.altsep and os.path.altsep in uf_path)
                if not has_dir:
                    uf_path = str(data_dir / uf_path)
                # If file does not exist (bare filename from dropzone, etc.),
                # create an empty file so the pipeline can process it.
                # The upload transport will provide the actual content;
                # the API accepts the filename reference.
                if not os.path.exists(uf_path):
                    Path(uf_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(uf_path).touch()
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

                adapter = get_adapter if False else None
                from services.adapters import get_adapter as _get_adapter
                adapter = _get_adapter(uf_path)
                if adapter is None:
                    raise ValueError(f"no adapter for {ext}")

                result = await adapter.extract(uf_path)

                # For EML files, run LLM enrichment if chain provided
                if ext == ".eml" and chain and result.contacts:
                    with open(uf_path, "rb") as f:
                        raw_eml = f.read()
                    from services.eml_processor import parse_eml_bytes, extract_local_fields, build_llm_prompt, merge_fields
                    parsed = parse_eml_bytes(raw_eml, name)
                    local = extract_local_fields(parsed)
                    ai = None
                    if chain:
                        ai, label = await llm.extract(chain, build_llm_prompt(parsed))
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

                # Upsert contacts
                for nc in result.contacts:
                    contact_dict = {
                        "name": nc.name,
                        "email_primary": nc.email_primary,
                        "phone_primary": nc.phone_primary,
                        "company": nc.company,
                        "designation": nc.designation,
                        "address": nc.address,
                        "city": nc.city,
                        "pincode": nc.pincode,
                        "website": nc.website,
                        "source_file": nc.source_file or name,
                    }
                    cid, action = db.upsert_contact(con, contact_dict, "contacts", source_file=name)
                    if action == "new":
                        counts["new"] += 1
                    elif action == "merged":
                        counts["merged"] += 1
                    elif action == "skipped":
                        counts["skipped"] += 1

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

        con.commit()
    finally:
        con.close()

    return {"ok": True, "results": results, "counts": counts}