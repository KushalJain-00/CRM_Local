# app.py — local FastAPI server. Loopback only, no auth, no cloud.
import asyncio
import os
import subprocess
import sys
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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import db
import pipeline

from api import system, settings, intake as api_intake, jobs, staged, contacts, emails, quality, history

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
STATIC = BASE / "static"

# Loopback hosts for SEC-03 (D-028c): rejected before Host is considered.
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}

# Lifespan context manager replacing the deprecated on_event("startup") / on_event("shutdown").
# Guarantees initialization runs before the first request and cleanup on shutdown.
# Required for TestClient and uvicorn to properly exercise the startup path.
@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Never delete -wal/-shm: they may hold the last committed transactions
    # after a crash. SQLite recovers them automatically on first open.
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

class ConfigIn(BaseModel):
    crm_dir: str | None = None
    eml_dir: str | None = None
    chain: list | None = None
    watch: bool | None = None
    watch_interval: int | None = None
    theme: str | None = None

class FolderIn(BaseModel):
    initial: str = ""

# SEC-09 (D-028c): force config.json to 0600 at startup is now handled by the
# lifespan context manager below, which guarantees db.init() runs before the first
# request and config.lock_down() runs at startup.

# ── routes that STAY in app.py (composition root only) ────────────────────

@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")

# /api/status is served by api/system.py (registered below).

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
app.include_router(contacts.router, prefix="/api", tags=["contacts"])
app.include_router(emails.router, prefix="/api", tags=["emails"])
app.include_router(quality.router, prefix="/api", tags=["quality"])
app.include_router(history.router, prefix="/api", tags=["history"])

# ── static assets: mounted above main() so `python app.py` (and the frozen
#    exe, which execs this module as __main__) registers the mount before
#    uvicorn.run() blocks. Mounting after `if __name__ == "__main__"` never ran.

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
