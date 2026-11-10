# app.py — local FastAPI server. Loopback only, no auth, no cloud.
import asyncio
import os
import subprocess
import sys
import uuid
from urllib.parse import urlsplit

# Windowed PyInstaller exe: no console → std streams are None, which crashes
# uvicorn's logging formatter. Must run before third-party imports.
if getattr(sys, "frozen", False) and sys.stderr is None:
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import db
import export
import llm
import pipeline
import intake

from api import system, settings, intake as api_intake, jobs, staged

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
STATIC = BASE / "static"


# Canonical data directory: .crm_local on POSIX, APPDATA/CRM_Local on Windows.
# Must match config.data_dir() and db.db_path() for cross-platform consistency.
def data_dir() -> Path:
    if os.name == "nt":
        d = Path(os.environ.get("APPDATA") or Path.home()) / "CRM_Local"
    else:
        d = Path.home() / ".crm_local"
    d.mkdir(parents=True, exist_ok=True)
    return d


# Loopback hosts for SEC-03 (D-028c): rejected before Host is considered.
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}


# Lifespan context manager replacing the deprecated on_event("startup") / on_event("shutdown").
# Guarantees initialization runs before the first request and cleanup on shutdown.
# Required for TestClient and uvicorn to properly exercise the startup path.
@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: clean up any stale WAL/SHM files, then initialize database, config,
    # and optional watch pipeline
    _db_path = Path(config.db_path("crm"))
    for suffix in ("-wal", "-shm"):
        sidecar = _db_path.with_name(_db_path.name + suffix)
        if sidecar.exists():
            sidecar.unlink()
    db.init()
    config.lock_down()
    if config.load().get("watch"):
        pipeline.start_watch()
    yield


app = FastAPI(title="CRM Local", openapi_url=None, lifespan=_lifespan)  # type: ignore


def _allowed_origins(host_header: str) -> set[str]:
    port = urlsplit("//" + host_header).port if host_header else None
    env_port = os.environ.get("PORT", "")
    ports = {p for p in (port, int(env_port) if env_port.isdigit() else None) if p} or {80}
    origins = {f"http://{h}:{p}" for h in ("127.0.0.1", "localhost") for p in ports}
    if port in (None, 80):
        # Browsers omit the default port in the Origin header.
        origins.update({"http://127.0.0.1", "http://localhost"})
    return origins


@app.middleware("http")
async def security_headers(request, call_next):
    origin = request.headers.get("origin")
    if origin is not None and origin not in _allowed_origins(request.headers.get("host", "")):
        return JSONResponse({"detail": "origin not allowed"}, status_code=403)
    host = request.headers.get("host")
    if host is not None and (urlsplit("//" + host).hostname or "") not in _LOOPBACK_HOSTS:
        return JSONResponse({"detail": "host not allowed"}, status_code=403)
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


# SEC-01 / D-028a: key material never leaves the server on any config or
# settings response (GET *and* POST echo). Reads return each chain credential
# with a stable `id`, `api_key_set` (bool) and `api_key` replaced by
# MASKED_KEY. Writes are only-set-on-change: "", absent or MASKED_KEY keeps
# the stored key; any other value replaces it. Credentials omitted from a
# write payload are deleted (per-credential delete); unknown ids are created
# as given. (Contract: docs/SECURITY_REVIEW.md SEC-01 + D-028a; the Phase-2
# chain-absence from INTERFACE_CONTRACTS §4.12 lands with /api/providers.)
MASKED_KEY = "********"


def _mask_chain(chain: list | None) -> list:
    masked = []
    for i, entry in enumerate(chain or []):
        if not isinstance(entry, dict):
            continue
        e = dict(entry)
        has_key = bool(e.get("api_key"))
        e["id"] = str(e["id"]) if e.get("id") is not None else str(i)
        e["api_key_set"] = has_key
        e["api_key"] = MASKED_KEY if has_key else ""
        masked.append(e)
    return masked


def _mask_cfg(cfg: dict) -> dict:
    out = dict(cfg)
    out["chain"] = _mask_chain(out.get("chain"))
    return out


def _merge_chain(incoming: list | None, stored: list | None) -> list:
    stored = [e for e in (stored or []) if isinstance(e, dict)]
    for i, entry in enumerate(stored):
        if entry.get("id") is None:
            # Legacy entries: positional id, same convention as the read side,
            # so a GET→POST round-trip of an old config matches credentials.
            entry["id"] = str(i)
    by_id = {str(e["id"]): e for e in stored}
    merged = []
    for i, entry in enumerate(incoming or []):
        if not isinstance(entry, dict):
            raise HTTPException(422, "chain entries must be objects")
        e = dict(entry)
        key = e.get("api_key")
        if key is None:
            key = ""
        if not isinstance(key, str):
            raise HTTPException(422, "api_key must be a string")
        eid = str(e["id"]) if e.get("id") is not None else None
        old = by_id.get(eid) if eid is not None else (stored[i] if i < len(stored) else None)
        if key in ("", MASKED_KEY):
            e["api_key"] = (old or {}).get("api_key", "")
        e.pop("api_key_set", None)  # derived flag, recomputed on read
        e["id"] = eid if eid is not None else ((old or {}).get("id") or uuid.uuid4().hex[:8])
        merged.append(e)
    return merged


# SEC-09 (D-028c): force config.json to 0600 at startup is now handled by the
# lifespan context manager below, which guarantees db.init() runs before the first
# request and config.lock_down() runs at startup.


# ── routes that STAY in app.py (composition root only) ────────────────────

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


# ── /api/config retired → hard 410 (D-011) ────────────────────────────────

@app.get("/api/config")
async def get_config_retired():
    return JSONResponse({"error": "CONFIG_RETIRED", "detail": "use /api/settings instead"}, status_code=410)


@app.post("/api/config")
async def set_config_retired(body: ConfigIn):
    return JSONResponse({"error": "CONFIG_RETIRED", "detail": "use /api/settings instead"}, status_code=410)


# ── routes moved to api/ packages (D-010) ────────────────────────────────

app.include_router(system.router, prefix="/api", tags=["system"])
app.include_router(staged.router, prefix="/api", tags=["staged"])
app.include_router(settings.router, prefix="/api", tags=["settings"])
app.include_router(api_intake.router, prefix="/api", tags=["intake"])
app.include_router(jobs.router, prefix="/api", tags=["jobs"])

# Keep autostart inline (Windows-only, stays in app.py per D-010 §2.1)
@app.post("/api/autostart")
async def set_autostart(body: dict):
    enabled = bool(body.get("enabled"))
    if os.name != "nt":
        return {"ok": False, "error": "autostart is Windows-only"}
    # Only a frozen exe can autostart; python.exe would launch without the script.
    if not getattr(sys, "frozen", False):
        return {"ok": False, "error": "autostart is available in the installed app only"}
    import threading
    import webbrowser
    path = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "CRM_Local.cmd"
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


# ── static assets (see mount at end of module) ────────────────


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

app.mount("/static", StaticFiles(directory=STATIC), name="static")
