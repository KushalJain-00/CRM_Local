# pipeline.py — scan folders, extract contacts, keep both databases current.
import asyncio
import os
import threading
from collections import deque
from datetime import datetime
from email import policy
from email.parser import BytesHeaderParser

import config
import db
import llm
import parse
from services.eml_processor import (
    build_llm_prompt, extract_local_fields, merge_fields, parse_eml_bytes,
)

CRM_EXTS = (".xlsx", ".xls", ".csv", ".pdf")
EML_EXTS = (".eml",)
LOW_CONFIDENCE = 0.5
# SEC-07 (D-028): the scan path had no limits at all. shortcut: files deeper
# than MAX_SCAN_DEPTH or beyond MAX_SCAN_FILES are silently skipped — raise
# the caps if a legitimate archive needs more.
MAX_SCAN_DEPTH = 12
MAX_SCAN_FILES = 20_000
MAX_SCAN_SIZE = 10 * 1024 * 1024  # matches intake.MAX_FILE_SIZE


class RunState:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.running = False
        self.which = ""
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.log: deque = deque(maxlen=400)
        self.stats = {"files": 0, "new": 0, "merged": 0, "duplicates": 0, "errors": 0}
        self.watch_task: asyncio.Task | None = None

    def say(self, level: str, msg: str) -> None:
        self.log.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "msg": msg,
        })

    def snapshot(self) -> dict:
        return {
            "running": self.running,
            "which": self.which,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "stats": dict(self.stats),
            "log": list(self.log),
        }


STATE = RunState()


def _files(directory: str, exts: tuple[str, ...]) -> list[str]:
    if not directory or not os.path.isdir(directory):
        return []
    found = []
    base_depth = directory.rstrip(os.sep).count(os.sep)
    for root, dirs, names in os.walk(directory):
        depth = root.count(os.sep) - base_depth
        if depth < MAX_SCAN_DEPTH:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
        else:
            dirs[:] = []
        for name in names:
            if name.startswith("~$") or name.startswith("."):
                continue
            if name.lower().endswith(exts):
                if len(found) >= MAX_SCAN_FILES:
                    return found
                found.append(os.path.join(root, name))
    return found


def _eml_sort_key(path: str) -> tuple:
    """Order by the email's own Date header; fall back to mtime then name."""
    try:
        with open(path, "rb") as fh:
            headers = BytesHeaderParser(policy=policy.default).parse(fh)
        date = headers.get("Date")
        if date:
            parsed = date.datetime if hasattr(date, "datetime") else None
            if parsed:
                return (0, parsed.timestamp(), path)
    except Exception:
        pass
    try:
        return (1, os.path.getmtime(path), path)
    except OSError:
        return (2, 0.0, path)


def _pending(directory: str, which: str, exts: tuple[str, ...]) -> list[str]:
    paths = _files(directory, exts)
    if which == "eml":
        paths.sort(key=_eml_sort_key)
    else:
        paths.sort(key=lambda p: os.path.basename(p).lower())
    con = db.connect(which)
    try:
        out = []
        for path in paths:
            try:
                st = os.stat(path)
            except OSError:
                continue
            if st.st_size > MAX_SCAN_SIZE:
                # SEC-07: skip + record as error so oversized files are never
                # read whole (OOM) and stop being counted as pending.
                db.mark_processed(
                    con, path, st.st_size, st.st_mtime, "error",
                    f"file exceeds {MAX_SCAN_SIZE // (1024 * 1024)}MB scan size cap",
                )
                con.commit()
                continue
            if not db.is_processed(con, path, st.st_size, st.st_mtime):
                out.append(path)
        return out
    finally:
        con.close()


def pending_counts() -> dict:
    cfg = config.load()
    return {
        "crm": len(_pending(cfg["crm_dir"], "crm", CRM_EXTS)),
        "eml": len(_pending(cfg["eml_dir"], "eml", EML_EXTS)),
    }


async def _process_eml(path: str, con, index: db.DedupIndex, chain: list,
                       cfg: dict | None = None) -> None:
    cfg = cfg or config.load()
    from services.prompts.store import text as prompt_text
    name = os.path.basename(path)
    with open(path, "rb") as fh:
        raw = fh.read()
    parsed = parse_eml_bytes(raw, name)
    local = extract_local_fields(parsed)

    ai = None
    if chain:
        ai, label = await llm.extract(chain, build_llm_prompt(parsed),
                                      system=prompt_text("eml"),
                                      reliability=cfg.get("reliability"))
        if ai:
            STATE.say("info", f"{name}: LLM fields via {label}")
        else:
            STATE.say("warn", f"{name}: LLM skipped ({label}) — local fields only")

    fields = merge_fields(local, ai)
    contact = {
        "name": fields.get("name"),
        "email_primary": fields.get("email"),
        "email_secondary": None,
        "phone_primary": fields.get("phone_primary"),
        "phone_secondary": fields.get("phone_secondary"),
        "company": fields.get("company"),
        "designation": fields.get("designation"),
        "address": fields.get("address"),
        "city": fields.get("city"),
        "pincode": fields.get("pincode"),
        "website": fields.get("website"),
    }
    email_id = db.insert_email(con, parsed, path)
    if not contact["email_primary"] and not contact["phone_primary"]:
        STATE.say("warn", f"{name}: no email or phone found — email logged, contact not staged")
        return
    from services import staging
    contact["source_file"] = name
    _ai_of = {"email_primary": "email"}  # merge_fields maps ai.email → email_primary
    contact["field_origin"] = {k: ("ai" if (ai and ai.get(_ai_of.get(k, k))) else "local")
                               for k in ("name", "email_primary", "phone_primary", "company",
                                         "designation", "address", "city", "pincode", "website")
                               if contact.get(k)}
    contact["to_emails"] = getattr(parsed, "to_emails", None)
    contact["cc_emails"] = getattr(parsed, "cc_emails", None)
    contact["bcc_emails"] = getattr(parsed, "bcc_emails", None)
    staged = staging.stage_contacts(con, [contact], source_type="eml",
                                    source_file=name, source_email_id=email_id)
    new_ids = [r[0] for r in con.execute(
        "SELECT id FROM staged_contacts WHERE source_email_id = ?", (email_id,)).fetchall()]
    for sid in new_ids:
        con.execute(
            "INSERT OR IGNORE INTO email_staged_links (email_id, staged_contact_id, created_at)"
            " VALUES (?, ?, ?)", (email_id, sid, db.now_iso()))
    STATE.stats["new"] += staged["staged"]
    index.add(contact["email_primary"], contact["phone_primary"], contact["name"])


async def _process_doc(path: str, con, index: db.DedupIndex, chain: list | None = None,
                       cfg: dict | None = None) -> None:
    name = os.path.basename(path)
    table = parse.read_table(path)
    mapping, unmatched, confidence = parse.map_headers(table["headers"])
    if confidence < LOW_CONFIDENCE:
        STATE.say(
            "warn",
            f"{name}: low column confidence ({int(confidence * 100)}%) — "
            f"unmapped: {', '.join(unmatched[:4]) or 'none'}",
        )
        if chain and await _ai_document_assist(name, table, mapping, unmatched,
                                               confidence, con, index, chain, cfg):
            return  # AI resolved the headers; deterministic rows would repeat.
    if not mapping:
        STATE.say("warn", f"{name}: no recognisable contact columns — skipped")
        return
    added = 0
    from services import staging
    batch = []
    for row in table["rows"]:
        contact = parse.row_to_contact(row, mapping)
        if not contact:
            continue
        contact["source_file"] = name
        contact["source_row"] = row.get("_row") if isinstance(row, dict) else None
        batch.append(contact)
    staged = staging.stage_contacts(con, batch, source_type=(
        os.path.splitext(name)[1].lstrip(".").lower() or "csv"), source_file=name)
    STATE.stats["new"] += staged["staged"]
    STATE.stats["duplicates"] += staged["duplicates"]
    added = staged["staged"]
    STATE.say("ok", f"{name}: {added} contact(s) staged from {len(table['rows'])} row(s)")


# Part 4: AI assists documents only when deterministic mapping is weak — this
# is the contact-prompt workflow. Output is gated by services/contract
# (crm-extraction.v1); invalid output means no AI rows, never partial writes.
async def _ai_document_assist(name, table, mapping, unmatched, confidence,
                             con, index, chain, cfg) -> bool:
    from services.ai_assist import assist_document
    from services import staging
    table = dict(table, mapped=dict(mapping), confidence=round(confidence, 2))
    cfg_eff = cfg or config.load()
    ai_contacts = await assist_document(
        table, name=name, chain=chain, cfg=cfg_eff,
        source_type="spreadsheet", say=STATE.say)
    if not ai_contacts:
        STATE.say("warn", f"{name}: AI assist unavailable or invalid — "
                          "keeping deterministic results")
        return False
    staged = staging.stage_contacts(
        con, ai_contacts,
        source_type=name.rsplit(".", 1)[-1].lower() if "." in name else "csv",
        source_file=name)
    STATE.say("ok", f"{name}: AI assist — {staged['staged']} contact(s) staged "
                    f"({staged['needs_review']} need review)")
    return True


async def scan(which: str = "all") -> dict:
    """Scan 'crm', 'eml', or 'all'. Idempotent: unchanged files are skipped."""
    if STATE.lock.locked():
        return {"ok": False, "error": "a scan is already running"}
    async with STATE.lock:
        cfg = config.load()
        STATE.running = True
        STATE.which = which
        STATE.started_at = datetime.now().isoformat(timespec="seconds")
        STATE.finished_at = None
        STATE.stats = {"files": 0, "new": 0, "merged": 0, "duplicates": 0, "errors": 0}
        STATE.say("info", f"Scan started ({which})")
        targets = ["eml", "crm"] if which == "all" else [which]
        try:
            for silo in targets:
                directory = cfg["eml_dir"] if silo == "eml" else cfg["crm_dir"]
                exts = EML_EXTS if silo == "eml" else CRM_EXTS
                if not directory or not os.path.isdir(directory):
                    STATE.say("warn", f"{silo}: folder not set or missing — skipped")
                    continue
                paths = _pending(directory, silo, exts)
                STATE.say("info", f"{silo}: {len(paths)} new file(s)")
                con = db.connect(silo)
                index = db.DedupIndex.load(
                    con, "eml_contacts" if silo == "eml" else "contacts",
                    with_names=(silo == "eml"),
                )
                try:
                    for path in paths:
                        STATE.stats["files"] += 1
                        before = STATE.stats["new"]
                        try:
                            st = os.stat(path)
                            if silo == "eml":
                                await _process_eml(path, con, index, cfg["chain"], cfg)
                            else:
                                await _process_doc(path, con, index, cfg["chain"], cfg)
                            con.commit()
                            db.mark_processed(
                                con, path, st.st_size, st.st_mtime, "ok",
                                contacts_found=STATE.stats["new"] - before,
                            )
                            con.commit()
                        except Exception as exc:
                            STATE.stats["errors"] += 1
                            STATE.say("error", f"{os.path.basename(path)}: {exc}")
                            try:
                                st = os.stat(path)
                                db.mark_processed(
                                    con, path, st.st_size, st.st_mtime, "error", str(exc)[:300]
                                )
                                con.commit()
                            except Exception:
                                pass
                finally:
                    con.close()
            STATE.say("ok", "Scan finished")
        finally:
            STATE.running = False
            STATE.finished_at = datetime.now().isoformat(timespec="seconds")
        return {"ok": True, "stats": dict(STATE.stats)}


async def _watch_loop() -> None:
    while True:
        cfg = config.load()
        if not cfg.get("watch"):
            return
        try:
            await scan("all")
        except Exception as exc:
            STATE.say("error", f"watch: {exc}")
        await asyncio.sleep(max(10, int(cfg.get("watch_interval", 30))))


def start_watch() -> None:
    loop = asyncio.get_running_loop()
    if STATE.watch_task is None or STATE.watch_task.done():
        STATE.watch_task = loop.create_task(_watch_loop())


def stop_watch() -> None:
    if STATE.watch_task and not STATE.watch_task.done():
        STATE.watch_task.cancel()
    STATE.watch_task = None


def folder_picker(initial: str = "") -> str:
    """Native folder dialog. Runs in a thread because tkinter blocks."""
    result: dict[str, str] = {}

    def _run():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            result["path"] = filedialog.askdirectory(initialdir=initial or None) or ""
            root.destroy()
        except Exception as exc:
            result["error"] = str(exc)

    thread = threading.Thread(target=_run)
    thread.start()
    thread.join(timeout=180)
    return result.get("path", "")
