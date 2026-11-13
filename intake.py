# intake.py — Universal file intake for CRM_Local.
# Upload channel: spool/limits/validation here; the extraction lifecycle
# lives in services/extract.py (shared with the folder scan).
import os
import re
import logging

import config
import db
from services import staging
from services.extract import process_source
from services.limits import MAX_TOTAL_SIZE

logger = logging.getLogger(__name__)

_SPOOL_RE = re.compile(r"^\d+~\d+~")


def _display_name(path: str) -> str:
    # Spool files arrive as "<pid>~<i>~<original>" — show the original.
    return _SPOOL_RE.sub("", os.path.basename(path))


async def universal_intake(files, chain=None, options=None):
    """Process a batch of mixed-format files through the unified extraction pipeline."""
    chain = chain or []
    options = options or {}
    results = []
    counts = {"new": 0, "duplicate": 0, "merged": 0, "error": 0, "skipped": 0}
    total_size = 0

    con = db.connect("crm")
    total_contacts = 0
    run_id = None
    try:
        run_id = staging.open_extraction_run(con, files_processed=len(files))
        for uf_path in files:
            name = _display_name(uf_path)
            try:
                # A bare filename is relative to the data directory (a client
                # that has no full path may send one).
                data_dir = os.path.realpath(str(config.data_dir()))
                if not (os.path.sep in uf_path or (os.path.altsep and os.path.altsep in uf_path)):
                    uf_path = os.path.join(data_dir, uf_path)
                if not os.path.exists(uf_path):
                    raise ValueError(f"file not found: {name}")
                size = os.path.getsize(uf_path)
                total_size += size
                if total_size > MAX_TOTAL_SIZE:
                    raise ValueError(f"total upload size exceeds {MAX_TOTAL_SIZE // (1024 * 1024)}MB")

                outcome = await process_source(
                    con, uf_path, chain=chain,
                    extraction_run_id=run_id, source_name=name)

                if outcome.status == "OK":
                    total_contacts += outcome.staged
                    counts["new"] += outcome.staged
                    counts["skipped"] += outcome.needs_review
                    results.append({
                        "file": name,
                        "status": "OK",
                        "contacts_found": outcome.contacts_found,
                        "warnings": outcome.warnings,
                        "adapter": outcome.adapter,
                    })
                else:
                    counts["error"] += 1
                    results.append({"file": name, "status": "ERROR", "error": outcome.error})
            except Exception as exc:
                counts["error"] += 1
                results.append({"file": name, "status": "ERROR", "error": str(exc)})
                try:
                    size = os.path.getsize(uf_path) if os.path.exists(uf_path) else 0
                    db.mark_processed(con, uf_path, size,
                                      os.path.getmtime(uf_path) if os.path.exists(uf_path) else 0,
                                      "error", str(exc)[:300])
                except Exception:
                    pass

        if run_id is not None:
            staging.close_extraction_run(
                con, run_id, total_contacts,
                status="completed" if counts["error"] == 0 else "completed_with_errors")
        con.commit()
    finally:
        con.close()

    # Top-level ok means "request handled"; per-file failures are reported in
    # results[].status == "ERROR" (frontend contract — see tests/test_intake.py).
    return {"ok": True, "results": results, "counts": counts}
