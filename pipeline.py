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
    for root, dirs, names in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in names:
            if name.startswith("~$") or name.startswith("."):
                continue
            if name.lower().endswith(exts):
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


async def _process_eml(path: str, con, index: db.DedupIndex, chain: list) -> None:
    name = os.path.basename(path)
    with open(path, "rb") as fh:
        raw = fh.read()
    parsed = parse_eml_bytes(raw, name)
    local = extract_local_fields(parsed)

    ai = None
    if chain:
        ai, label = await llm.extract(chain, build_llm_prompt(parsed))
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
    if not contact["email_primary"] and not contact["phone_primary"]:
        STATE.say("warn", f"{name}: no email or phone found — skipped")
        return

    email_id = db.insert_email(con, parsed, path)
    reason = index.duplicate_reason(
        contact["email_primary"], contact["phone_primary"], contact["name"]
    )
    if reason:
        STATE.stats["duplicates"] += 1
        STATE.say("skip", f"{name}: duplicate by {reason} — merged into existing")
        contact_id, _ = db.upsert_contact(
            con, contact, "eml_contacts", source_file=name
        )
    else:
        STATE.stats["new"] += 1
        contact_id = db.insert_eml_contact(con, email_id, contact, "new", name)
    index.add(contact["email_primary"], contact["phone_primary"], contact["name"])

    # Push into the CRM silo (same unified DB now), enriching the existing row.
    try:
        _, action = db.upsert_contact(con, contact, "contacts", source_file=name)
        if action == "merged":
            STATE.stats["merged"] += 1
        db.mark_pushed(con, contact_id)
    except Exception as e:
        STATE.say("warn", f"{name}: CRM push failed: {e}")


def _process_doc(path: str, con, index: db.DedupIndex) -> None:
    name = os.path.basename(path)
    table = parse.read_table(path)
    mapping, unmatched, confidence = parse.map_headers(table["headers"])
    if confidence < LOW_CONFIDENCE:
        STATE.say(
            "warn",
            f"{name}: low column confidence ({int(confidence * 100)}%) — "
            f"unmapped: {', '.join(unmatched[:4]) or 'none'}",
        )
    if not mapping:
        STATE.say("warn", f"{name}: no recognisable contact columns — skipped")
        return
    added = 0
    for row in table["rows"]:
        contact = parse.row_to_contact(row, mapping)
        if not contact:
            continue
        reason = index.duplicate_reason(
            contact["email_primary"], contact["phone_primary"], None
        )
        if reason:
            STATE.stats["duplicates"] += 1
            action = "merged"
        else:
            action = "new"
        _, result = db.upsert_contact(con, contact, "contacts", source_file=name)
        index.add(contact["email_primary"], contact["phone_primary"], None)
        if result == "new":
            STATE.stats["new"] += 1
            added += 1
        elif action == "merged" or result == "merged":
            STATE.stats["merged"] += 1
    STATE.say("ok", f"{name}: {added} new contact(s) from {len(table['rows'])} row(s)")


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
                                await _process_eml(path, con, index, cfg["chain"])
                            else:
                                _process_doc(path, con, index)
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
