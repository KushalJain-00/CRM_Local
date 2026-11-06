# app.py — local FastAPI server. Loopback only, no auth, no cloud.
import asyncio
import os
import subprocess
import sys

# Windowed PyInstaller exe: no console → std streams are None, which crashes
# uvicorn's logging formatter. Must run before third-party imports.
if getattr(sys, "frozen", False) and sys.stderr is None:
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import db
import export
import llm
import pipeline
import intake

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
STATIC = BASE / "static"

app = FastAPI(title="CRM Local", openapi_url=None)

@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


class ScanIn(BaseModel):
    which: str = "all"


class ConfigIn(BaseModel):
    crm_dir: str | None = None
    eml_dir: str | None = None
    chain: list | None = None
    watch: bool | None = None
    watch_interval: int | None = None
    theme: str | None = None


class EntryIn(BaseModel):
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""
    enabled: bool = True


class FolderIn(BaseModel):
    initial: str = ""


class ContactIn(BaseModel):
    fields: dict


def _table(which: str) -> str:
    if which == "crm":
        return "contacts"
    if which == "eml":
        return "eml_contacts"
    raise HTTPException(400, "which must be 'crm' or 'eml'")


@app.on_event("startup")
async def _startup() -> None:
    db.init()
    if config.load().get("watch"):
        pipeline.start_watch()


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
async def status():
    counts = db.counts()
    try:
        pending = pipeline.pending_counts()
    except Exception:
        pending = {"crm": 0, "eml": 0}
    return {
        "counts": counts,
        "pending": pending,
        "run": pipeline.STATE.snapshot(),
        "providers": llm.PROVIDERS,
        "version": "1.0.0",
    }


@app.get("/api/config")
async def get_config():
    cfg = config.load()
    cfg["config_path"] = str(config.config_path())
    cfg["crm_db_path"] = str(config.db_path("crm"))
    cfg["eml_db_path"] = str(config.db_path("eml"))
    return cfg


@app.post("/api/config")
async def set_config(body: ConfigIn):
    cfg = config.load()
    for key, value in body.model_dump(exclude_none=True).items():
        cfg[key] = value
    config.save(cfg)
    if cfg.get("watch"):
        pipeline.start_watch()
    else:
        pipeline.stop_watch()
    return cfg


@app.post("/api/scan")
async def start_scan(body: ScanIn):
    if body.which not in ("crm", "eml", "all"):
        raise HTTPException(400, "which must be crm, eml or all")
    asyncio.create_task(pipeline.scan(body.which))
    return {"ok": True, "started": body.which}


@app.post("/api/intake")
async def universal_intake_endpoint(files: list[str] = None, paths: list[str] = None):
    """Universal file intake: accepts file paths, processes all formats."""
    file_paths = paths or files or []
    if not file_paths:
        raise HTTPException(400, "No files provided")
    if len(file_paths) > 50:
        raise HTTPException(400, "Too many files (max 50)")
    result = await intake.universal_intake(file_paths)
    return result


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: int):
    """Get job status (simplified — returns completed)."""
    return {"job_id": job_id, "state": "done", "progress": {"done": 1, "total": 1}, "results": []}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: int):
    """Cancel a running job (best-effort)."""
    return {"job_id": job_id, "state": "cancelled"}


@app.get("/api/settings")
async def get_settings():
    cfg = config.load()
    return cfg


@app.post("/api/settings")
async def update_settings(body: ConfigIn):
    cfg = config.load()
    for key, value in body.model_dump(exclude_none=True).items():
        cfg[key] = value
    config.save(cfg)
    return cfg


@app.get("/api/contacts")
async def contacts(which: str = "crm", q: str = "", page: int = 1, size: int = 50):
    table = _table(which)
    con = db.connect(which)
    try:
        rows, total = db.list_contacts(con, table, q, page, size)
    finally:
        con.close()
    return {"rows": rows, "total": total, "page": page, "size": size}


@app.patch("/api/contacts/{which}/{contact_id}")
async def edit_contact(which: str, contact_id: int, body: ContactIn):
    table = _table(which)
    con = db.connect(which)
    try:
        ok = db.update_contact(con, table, contact_id, body.fields)
        con.commit()
    finally:
        con.close()
    if not ok:
        raise HTTPException(404, "contact not found")
    return {"ok": True}


@app.delete("/api/contacts/{which}/{contact_id}")
async def remove_contact(which: str, contact_id: int):
    table = _table(which)
    con = db.connect(which)
    try:
        ok = db.delete_contact(con, table, contact_id)
        con.commit()
    finally:
        con.close()
    if not ok:
        raise HTTPException(404, "contact not found")
    return {"ok": True}


@app.get("/api/export")
async def export_contacts(which: str = "crm"):
    table = _table(which)
    con = db.connect(which)
    try:
        rows, _ = db.list_contacts(con, table, "", 1, 100000)
    finally:
        con.close()
    data = export.contacts_to_xlsx(rows, "CRM Contacts" if which == "crm" else "EML Contacts")
    filename = f"{which}_contacts.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/pick-folder")
async def pick_folder(body: FolderIn):
    path = await asyncio.to_thread(pipeline.folder_picker, body.initial)
    if not path:
        return {"path": "", "cancelled": True}
    return {"path": path}


@app.post("/api/open-folder")
async def open_folder(body: FolderIn):
    path = body.initial
    if not path or not os.path.isdir(path):
        raise HTTPException(400, "folder does not exist")
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
    return {"ok": True}


@app.post("/api/test-llm")
async def test_llm(body: EntryIn):
    result = await llm.test_entry(body.model_dump())
    return {"ok": result == "ok", "result": result}


def _autostart_path() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "CRM_Local.cmd"


@app.post("/api/autostart")
async def set_autostart(body: dict):
    enabled = bool(body.get("enabled"))
    if os.name != "nt":
        return {"ok": False, "error": "autostart is Windows-only"}
    # Only a frozen exe can autostart; python.exe would launch without the script.
    if not getattr(sys, "frozen", False):
        return {"ok": False, "error": "autostart is available in the installed app only"}
    path = _autostart_path()
    try:
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'@echo off\r\nstart "" "{sys.executable}"\r\n', "utf-8")
        elif path.exists():
            path.unlink()
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    cfg = config.load()
    cfg["autostart"] = enabled
    config.save(cfg)
    return {"ok": True, "enabled": enabled}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _free_port(preferred: int = 8000, tries: int = 11) -> int:
    import socket
    for port in range(preferred, preferred + tries):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return preferred


def main() -> None:
    import uvicorn
    port = int(os.environ.get("PORT", 0)) or _free_port()
    host = "127.0.0.1"
    if getattr(sys, "frozen", False):
        import threading
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    else:
        print(f"\n  CRM Local — http://127.0.0.1:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
