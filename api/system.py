# api/system.py — health/status/autostart routes (INTERFACE_CONTRACTS §2.1).
import os

import sys
from pathlib import Path

from fastapi import APIRouter

import config
import db
import pipeline
import providers as _providers

router = APIRouter()

@router.get("/health")
async def health():
    # Catalogue #1: liveness probe — net-new for Phase 2 (§3).
    return {"ok": True}

@router.get("/status")
async def status():
    counts = db.counts()
    try:
        pending = pipeline.pending_counts()
    except Exception:
        pending = {"crm": 0, "eml": 0}
    # Never leak key material or non-serializable specs — id/name/protocol only.
    provider_ids = sorted(_providers.PROVIDERS)
    return {
        "counts": counts,
        "pending": pending,
        "run": pipeline.STATE.snapshot(),
        "providers": provider_ids,
        "version": "1.0.0",
    }

def _autostart_path() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "CRM_Local.cmd"

@router.post("/autostart")
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
