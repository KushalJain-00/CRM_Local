# api/settings.py — settings + providers (INTERFACE_CONTRACTS §2.1)
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, HTTPException

from pydantic import BaseModel

router = APIRouter()


class ProviderIn(BaseModel):
    id: Optional[str] = None
    model: str
    base_url: str = ""
    enabled: bool = True


class ModeIn(BaseModel):
    mode: str
    import_policy: str = "review_first"


MASKED_KEY = "********"


def _mask_chain(chain: list | None) -> list:
    masked = []
    for i, entry in enumerate(chain or []):
        if not isinstance(entry, dict):
            continue
        e = dict(entry)
        # Assign positional id for legacy entries that lack 'id'
        if e.get("id") is None:
            e["id"] = str(i)
        has_key = bool(e.get("api_key"))
        e["api_key_set"] = has_key
        e["api_key"] = MASKED_KEY if has_key else ""
        masked.append(e)
    return masked


def _mask_cfg(cfg: dict) -> dict:
    out = dict(cfg)
    out["chain"] = _mask_chain(out.get("chain"))
    return out


@router.get("/settings")
async def get_settings():
    import config
    cfg = _mask_cfg(config.load())
    cfg["config_path"] = str(config.config_path())
    cfg["crm_db_path"] = str(config.db_path("crm"))
    cfg["eml_db_path"] = str(config.db_path("eml"))
    return cfg


@router.post("/settings")
async def update_settings(body: dict):
    import config
    cfg = config.load()
    updates = body.model_dump(exclude_none=True) if hasattr(body, "model_dump") else body
    if "chain" in updates:
        # simple merge: new values replace stored by id, keep old ones
        # first, ensure all stored entries have an 'id' (legacy compat)
        stored = cfg.get("chain") or []
        for i, e in enumerate(stored):
            if not isinstance(e, dict):
                continue
            if e.get("id") is None:
                e["id"] = str(i)
        by_id = {str(e["id"]): e for e in stored if isinstance(e, dict)}
        new_chain = []
        for i, entry in enumerate(updates.get("chain") or []):
            if not isinstance(entry, dict):
                continue
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
            e.pop("api_key_set", None)
            e["id"] = eid if eid is not None else ((old or {}).get("id") or uuid.uuid4().hex[:8])
            new_chain.append(e)
        updates["chain"] = new_chain
    cfg.update(updates)
    config.save(cfg)
    return _mask_cfg(cfg)


@router.get("/providers")
async def list_providers():
    import config
    cfg = config.load()
    providers = cfg.get("chain", [])
    return _mask_chain(providers)


@router.post("/providers")
async def add_provider(body: ProviderIn):
    import config
    cfg = config.load()
    chain = cfg.get("chain", [])
    # assign new id
    new_id = body.id or str(len(chain))
    entry = {
        "id": new_id,
        "model": body.model,
        "base_url": body.base_url,
        "enabled": body.enabled,
    }
    # write-only api_key: if provided, store it; if absent, store empty (keep)
    if body.api_key is not None and body.api_key != "":
        entry["api_key"] = body.api_key
    chain.append(entry)
    cfg["chain"] = chain
    config.save(cfg)
    return _mask_chain(chain)


@router.patch("/providers/{provider_id}")
async def edit_provider(provider_id: str, body: ProviderIn):
    import config
    cfg = config.load()
    chain = cfg.get("chain", [])
    for entry in chain:
        if entry.get("id") == provider_id:
            entry["model"] = body.model if body.model else entry.get("model", "")
            entry["base_url"] = body.base_url if body.base_url else entry.get("base_url", "")
            entry["enabled"] = body.enabled if body.enabled is not None else entry.get("enabled", True)
            break
    else:
        raise HTTPException(404, "provider not found")
    cfg["chain"] = chain
    config.save(cfg)
    return _mask_chain(chain)


@router.delete("/providers/{provider_id}")
async def remove_provider(provider_id: str):
    import config
    cfg = config.load()
    chain = cfg.get("chain", [])
    new_chain = [e for e in chain if e.get("id") != provider_id]
    if len(new_chain) == len(chain):
        raise HTTPException(404, "provider not found")
    cfg["chain"] = new_chain
    config.save(cfg)
    return {"ok": True}


@router.post("/providers/{provider_id}/enable")
async def enable_provider(provider_id: str):
    import config
    cfg = config.load()
    chain = cfg.get("chain", [])
    for entry in chain:
        if entry.get("id") == provider_id:
            entry["enabled"] = True
            break
    else:
        raise HTTPException(404, "provider not found")
    cfg["chain"] = chain
    config.save(cfg)
    return _mask_chain(chain)


@router.post("/providers/{provider_id}/disable")
async def disable_provider(provider_id: str):
    import config
    cfg = config.load()
    chain = cfg.get("chain", [])
    for entry in chain:
        if entry.get("id") == provider_id:
            entry["enabled"] = False
            break
    else:
        raise HTTPException(404, "provider not found")
    cfg["chain"] = chain
    config.save(cfg)
    return _mask_chain(chain)


@router.get("/settings/mode")
async def get_mode():
    import config
    cfg = config.load()
    return {"mode": cfg.get("mode", "review_first"), "import_policy": cfg.get("import_policy", "review_first")}


@router.put("/settings/mode")
async def set_mode(body: ModeIn):
    import config
    cfg = config.load()
    cfg["mode"] = body.mode
    cfg["import_policy"] = body.import_policy
    config.save(cfg)
    return {"ok": True, "mode": body.mode, "import_policy": body.import_policy}