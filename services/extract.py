# services/extract.py — THE extraction lifecycle. One pipeline, two entry points.
#
# Upload (intake) and folder scan (pipeline) both call process_source():
#   adapter parse → deterministic Layer-1 → optional contract-validated AI →
#   normalized contacts → staging (human review) → email/ledger bookkeeping.
# Neither caller re-implements any step; both only decide *which* files and
# report per-file outcomes. Deterministic results are never discarded; the
# AI stage fills gaps and is gated by the crm-extraction.v1 contract.
import asyncio
import json
import os
from dataclasses import dataclass, field

import config
import db
import llm
from services import staging
from services.approval import approve_ids
from services.dedup import UNIQUE
from services.keys import record_keys
from services.adapters import (
    get_adapter, eml_to_normalized, NormalizedContact,
)
from services.eml_processor import (
    FIELD_KEYS, extract_local_fields, merge_fields, build_llm_prompt,
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
    imported: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def _mark_error(con, path: str, exc: Exception, *, ledger_path: str) -> None:
    try:
        st = os.stat(path)
        size, mtime = st.st_size, st.st_mtime
    except OSError:
        size, mtime = 0, 0
    try:
        db.mark_processed(con, ledger_path, size, mtime, "error", str(exc)[:300])
    except Exception:
        pass


def _enrich_documents(contacts, candidates, name):
    indexed = {}

    def index(contact):
        keys = record_keys(vars(contact))
        for key in ("email_key", "phone_key"):
            if keys[key]:
                indexed.setdefault((key, keys[key]), {})[id(contact)] = contact

    for contact in contacts:
        index(contact)
    for candidate in candidates:
        keys = record_keys(candidate)
        matches = {id(match): match for key in ("email_key", "phone_key")
                   for match in indexed.get((key, keys[key]), {}).values()}
        if matches:
            if len(matches) != 1:
                continue
            contact = next(iter(matches.values()))
            previous_email = record_keys(vars(contact))["email_key"]
            if previous_email and keys["email_key"] and previous_email != keys["email_key"]:
                continue
            for key, value in candidate.items():
                if key in ("field_origin", "field_evidence", "confidence") or not value or getattr(contact, key):
                    continue
                setattr(contact, key, value)
                contact.field_origin = {**(contact.field_origin or {}), key: "ai"}
                evidence = candidate["field_evidence"].get(key)
                if evidence:
                    contact.field_evidence = {**(contact.field_evidence or {}), key: evidence}
            index(contact)
        else:
            contact = NormalizedContact(source_file=name, **candidate)
            contacts.append(contact)
            index(contact)


def _grounded_eml(payload, parsed):
    if set(payload) != set(FIELD_KEYS):
        return False
    sender = f"{parsed.sender_name[:100]} {parsed.sender_email[:254]}"
    source = " ".join((parsed.signature_block or parsed.body_text[:2500]).casefold().split())
    sender = " ".join(sender.casefold().split())
    for key, value in payload.items():
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip() or len(value) > 500:
            return False
        values = value.split(",") if key == "phone_secondary" else [value]
        evidence = f"{sender} {source}" if key in ("name", "email") else source
        if any(not part.strip() or " ".join(part.casefold().split()) not in evidence for part in values):
            return False
    return True


async def process_source(con, path: str, *, chain: list | None = None,
                         cfg: dict | None = None, extraction_run_id: int | None = None,
                         source_name: str | None = None, policy: str | None = None,
                         uploaded: bool = False) -> FileOutcome:
    """Run the full lifecycle for one file. Never raises for per-file faults;
    the outcome carries status/error (a batch must survive a bad file).

    source_name overrides the display/ledger name for spooled uploads
    (e.g. "<pid>~<i>~original.csv" displays as "original.csv")."""
    cfg = cfg if cfg is not None else config.load()
    path = os.path.abspath(path)
    name = source_name or os.path.basename(path)
    ledger_path = path
    if uploaded:
        ledger_path = os.path.join(os.path.dirname(path), os.path.basename(path) + "-source", name)
    ext = os.path.splitext(name)[1].lower()

    if cfg.get("mode", "local_only") != "ai_enrichment":
        chain = []
    policy = policy or cfg.get("import_policy", "review_first")
    writing = False
    try:
        if os.path.getsize(path) > MAX_FILE_SIZE:
            raise ValueError(f"file too large (max {MAX_FILE_SIZE // (1024 * 1024)}MB)")

        adapter = get_adapter(path)
        if adapter is None:
            raise ValueError(f"no adapter for {ext}")

        # Adapters do synchronous decoding internally. Keep the HTTP event loop
        # available for status and cancellation while a file is being parsed.
        result = await asyncio.to_thread(lambda: asyncio.run(adapter.extract(path)))
        if result.error:
            raise ValueError(result.error)
        warnings = list(result.warnings)
        contacts = list(result.contacts)
        adapter_name = result.adapter or getattr(adapter, "name", "") or "unknown"

        # ── EML: email row + local/AI merge ──────────────────────────────
        source_email_id = None
        parsed = None
        if ext == ".eml":
            parsed = getattr(result, "parsed", None)
            if parsed is None:
                # Adapter kept the failure; surface it, never stage half an email.
                raise ValueError(warnings[0] if warnings else "eml parse failed")
            if chain:
                prompt = build_llm_prompt(parsed)

                def valid(payload):
                    return _grounded_eml(payload, parsed)

                ai, label = await llm.extract(
                    chain, prompt, system=prompt_store.text("eml"),
                    reliability=cfg.get("reliability"), validate_output=valid)
                if ai and valid(ai):
                    local = extract_local_fields(parsed)
                    merged = merge_fields(local, ai)
                    added = {key: value for key, value in ai.items() if value and not local.get(key)}
                    contact = eml_to_normalized(merged, added, source_file=name)
                    contact.field_evidence = {
                        ("email_primary" if key == "email" else key):
                        {"excerpt": value, "location": "email", "confidence": "low"}
                        for key, value in added.items()
                    }
                    contacts = [contact]
                else:
                    warnings.append(f"LLM skipped ({label}) — local fields only")
            for nc in contacts:
                nc.to_emails = parsed.to_emails or None
                nc.cc_emails = parsed.cc_emails or None
                nc.bcc_emails = parsed.bcc_emails or None

        # ── Documents (.csv/.xlsx/.xls/.pdf/.txt): deterministic + AI gap-fill ──
        elif chain:
            table = getattr(result, "table", None)
            if table is not None:
                ai_contacts, ai_notes = await assist_document(
                    table, name=name, chain=chain, cfg=cfg,
                    source_type="spreadsheet" if ext in (".xls", ".xlsx") else ext[1:])
                warnings.extend(ai_notes)
                _enrich_documents(contacts, ai_contacts, name)

        con.execute("SAVEPOINT extract_file")
        writing = True
        if parsed is not None:
            source_email_id = db.insert_email(con, parsed, None if uploaded else path, source_name=name)

        # ── Stage: every contact lands in the review queue ───────────────
        staged = staging.stage_contacts(
            con, [vars(nc) for nc in contacts],
            source_type=ext.lstrip(".") or "txt",
            source_file=name,
            source_email_id=source_email_id,
            extraction_run_id=extraction_run_id,
        )

        ids = staged["ids"]
        if source_email_id is not None:
            con.executemany(
                "INSERT OR IGNORE INTO email_staged_links"
                " (email_id, staged_contact_id, created_at) VALUES (?, ?, ?)",
                [(source_email_id, sid, db.now_iso()) for sid in ids])

        imported = 0
        if policy == "smart_import":
            for sid in ids:
                row = con.execute(
                    "SELECT * FROM staged_contacts WHERE id = ?", (sid,)
                ).fetchone()
                if (row["review_status"] == "READY" and row["dedup_status"] == UNIQUE
                        and not row["duplicate_candidate_ids"] and (row["email_key"] or row["phone_key"])
                        and not row["validation_warnings"]
                        and not any(value == "ai" for value in
                                    json.loads(row["field_evidence"]).get("field_origin", {}).values())
                        and staging._dedup_vs_canonical(con, dict(row))[1] == []):
                    imported += approve_ids(con, [sid])["approved"]

        st = os.stat(path)
        db.mark_processed(con, ledger_path, st.st_size, st.st_mtime, "ok", None,
                          contacts_found=staged["staged"])
        con.execute("RELEASE extract_file")
        writing = False
        return FileOutcome(path=path, name=name, status="OK", adapter=adapter_name,
                           contacts_found=len(contacts), staged=staged["staged"],
                           needs_review=staged["needs_review"],
                           duplicates=staged["duplicates"], imported=imported, warnings=warnings)

    except Exception as exc:
        if writing:
            con.execute("ROLLBACK TO extract_file")
            con.execute("RELEASE extract_file")
        _mark_error(con, path, exc, ledger_path=ledger_path)
        return FileOutcome(path=path, name=name, status="ERROR", error=str(exc))
