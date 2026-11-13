# services/extract.py — THE extraction lifecycle. One pipeline, two entry points.
#
# Upload (intake) and folder scan (pipeline) both call process_source():
#   adapter parse → deterministic Layer-1 → optional contract-validated AI →
#   normalized contacts → staging (human review) → email/ledger bookkeeping.
# Neither caller re-implements any step; both only decide *which* files and
# report per-file outcomes. Deterministic results are never discarded; the
# AI stage fills gaps and is gated by the crm-extraction.v1 contract.
import os
from dataclasses import dataclass, field

import config
import db
import llm
from services import staging, parse
from services.adapters import (
    get_adapter, eml_to_normalized, contract_to_normalized,
)
from services.eml_processor import (
    extract_local_fields, merge_fields, build_llm_prompt,
)
from services.prompts import store as prompt_store
from services.ai_assist import assist_document
from services.limits import MAX_FILE_SIZE


@dataclass
class FileOutcome:
    path: str                      # absolute
    name: str                      # basename
    status: str                    # "OK" | "ERROR"
    adapter: str = ""
    contacts_found: int = 0
    staged: int = 0
    needs_review: int = 0
    duplicates: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def _mark_error(con, path: str, exc: Exception) -> None:
    try:
        st = os.stat(path)
        size, mtime = st.st_size, st.st_mtime
    except OSError:
        size, mtime = 0, 0
    try:
        db.mark_processed(con, path, size, mtime, "error", str(exc)[:300])
    except Exception:
        pass


async def process_source(con, path: str, *, chain: list | None = None,
                         cfg: dict | None = None, extraction_run_id: int | None = None,
                         source_name: str | None = None) -> FileOutcome:
    """Run the full lifecycle for one file. Never raises for per-file faults;
    the outcome carries status/error (a batch must survive a bad file).

    source_name overrides the display/ledger name for spooled uploads
    (e.g. "<pid>~<i>~original.csv" displays as "original.csv")."""
    cfg = cfg if cfg is not None else config.load()
    path = os.path.abspath(path)
    name = source_name or os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()

    try:
        if os.path.getsize(path) > MAX_FILE_SIZE:
            raise ValueError(f"file too large (max {MAX_FILE_SIZE // (1024 * 1024)}MB)")

        adapter = get_adapter(path)
        if adapter is None:
            raise ValueError(f"no adapter for {ext}")

        result = await adapter.extract(path)
        warnings = list(result.warnings)
        contacts = list(result.contacts)
        adapter_name = result.adapter or getattr(adapter, "name", "") or "unknown"

        # ── EML: email row + local/AI merge ──────────────────────────────
        source_email_id = None
        if ext == ".eml":
            parsed = getattr(result, "parsed", None)
            if parsed is None:
                # Adapter kept the failure; surface it, never stage half an email.
                raise ValueError(warnings[0] if warnings else "eml parse failed")
            if chain:
                ai, label = await llm.extract(
                    chain, build_llm_prompt(parsed),
                    system=prompt_store.text("eml"),
                    reliability=cfg.get("reliability"))
                if ai:
                    merged = merge_fields(extract_local_fields(parsed), ai)
                    contacts = [eml_to_normalized(
                        merged, ai, source_file=name,
                        to_emails=parsed.to_emails or None,
                        cc_emails=parsed.cc_emails or None,
                        bcc_emails=parsed.bcc_emails or None)]
                else:
                    warnings.append(f"LLM skipped ({label}) — local fields only")
            source_email_id = db.insert_email(con, parsed, path)
            for nc in contacts:
                nc.to_emails = parsed.to_emails or None
                nc.cc_emails = parsed.cc_emails or None
                nc.bcc_emails = parsed.bcc_emails or None

        # ── Documents (.csv/.xlsx/.xls/.pdf/.txt): deterministic + AI gap-fill ──
        elif chain:
            try:
                table = parse.read_table(path)
            except Exception:
                table = None
            if table is not None:
                ai_contacts, ai_notes = await assist_document(
                    table, name=name, chain=chain, cfg=cfg,
                    source_type="spreadsheet")
                warnings.extend(ai_notes)
                contacts.extend(
                    contract_to_normalized(ac, source_file=name) for ac in ai_contacts)

        # ── Stage: every contact lands in the review queue ───────────────
        staged = staging.stage_contacts(
            con, [vars(nc) for nc in contacts],
            source_type=ext.lstrip(".") or "txt",
            source_file=name,
            source_email_id=source_email_id,
            extraction_run_id=extraction_run_id,
        )

        if source_email_id is not None:
            ids = [r[0] for r in con.execute(
                "SELECT id FROM staged_contacts WHERE source_email_id = ?",
                (source_email_id,)).fetchall()]
            for sid in ids:
                con.execute(
                    "INSERT OR IGNORE INTO email_staged_links"
                    " (email_id, staged_contact_id, created_at) VALUES (?, ?, ?)",
                    (source_email_id, sid, db.now_iso()))

        st = os.stat(path)
        db.mark_processed(con, path, st.st_size, st.st_mtime, "ok", None,
                          contacts_found=staged["staged"])
        return FileOutcome(path=path, name=name, status="OK", adapter=adapter_name,
                           contacts_found=len(contacts), staged=staged["staged"],
                           needs_review=staged["needs_review"],
                           duplicates=staged["duplicates"], warnings=warnings)

    except Exception as exc:
        _mark_error(con, path, exc)
        return FileOutcome(path=path, name=name, status="ERROR", error=str(exc))
