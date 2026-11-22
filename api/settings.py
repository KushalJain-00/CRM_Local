# api/settings.py — settings + providers (INTERFACE_CONTRACTS §2.1)

from typing import Any, Literal, Optional
import uuid

from fastapi import APIRouter, HTTPException

from pydantic import BaseModel

import config
import llm
import pipeline

RELIABILITY_FIELDS = llm.RELIABILITY_FIELDS
RELIABILITY_DESCRIPTIONS = llm.RELIABILITY_DESCRIPTIONS

router = APIRouter()

class ProviderIn(BaseModel):
    id: Optional[str] = None
    provider: Optional[str] = None
    model: str
    api_key: Optional[str] = None
    base_url: str = ""
    enabled: bool = True

class ModeIn(BaseModel):
    mode: Literal["local_only", "ai_enrichment"]
    import_policy: Literal["review_first", "always_stage", "smart_import"] = "review_first"

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
    out = {name: cfg[name] for name in config.DEFAULTS.keys() & cfg.keys()}
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
    updates = {key: value for key, value in body.items()
               if key in config.DEFAULTS or key == "watch_enabled"}
    if "watch_enabled" in updates:
        updates.setdefault("watch", updates.pop("watch_enabled"))
    if "watch" in updates and not isinstance(updates["watch"], bool):
        raise HTTPException(422, "watch must be a boolean")
    if "watch_interval" in updates:
        interval = updates["watch_interval"]
        if type(interval) is not int or not 10 <= interval <= 86400:
            raise HTTPException(422, "watch_interval must be an integer from 10 to 86400")
    if "mode" in updates or "import_policy" in updates:
        try:
            ModeIn(mode=updates.get("mode", cfg.get("mode", "local_only")),
                   import_policy=updates.get("import_policy", cfg.get("import_policy", "review_first")))
        except ValueError:
            raise HTTPException(422, "invalid extraction mode or import policy")
    if "reliability" in updates:
        updates["reliability"] = _clamp_reliability(updates.pop("reliability") or {})
    # prompts are edited only via /api/prompts — never through this surface
    updates.pop("prompts", None)
    if "chain" in updates:
        # simple merge: new values replace stored by id, keep old ones
        # first, ensure all stored entries have an 'id' (legacy compat)
        if not isinstance(updates["chain"], list):
            raise HTTPException(422, "chain must be a list")
        stored = cfg.get("chain") or []
        for i, e in enumerate(stored):
            if not isinstance(e, dict):
                continue
            if e.get("id") is None:
                e["id"] = str(i)
        by_id = {str(e["id"]): e for e in stored if isinstance(e, dict)}
        new_chain = []
        for entry in updates["chain"]:
            if not isinstance(entry, dict):
                continue
            e = dict(entry)
            key = e.get("api_key")
            if key is None:
                key = ""
            if not isinstance(key, str):
                raise HTTPException(422, "api_key must be a string")
            eid = str(e["id"]) if e.get("id") is not None else None
            old = by_id.get(eid) if eid is not None else None
            if key in ("", MASKED_KEY):
                e["api_key"] = (old or {}).get("api_key", "")
            e.pop("api_key_set", None)
            e["id"] = eid if eid is not None else ((old or {}).get("id") or uuid.uuid4().hex[:8])
            new_chain.append(e)
        updates["chain"] = new_chain
    cfg.pop("watch_enabled", None)
    cfg.update(updates)
    config.save(cfg)
    if updates.get("watch") is True:
        pipeline.start_watch()
    elif updates.get("watch") is False:
        pipeline.stop_watch()
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
    new_id = body.id or uuid.uuid4().hex[:8]
    if any(str(entry.get("id", i)) == new_id for i, entry in enumerate(chain)):
        raise HTTPException(409, "provider id already exists")
    entry = {
        "id": new_id,
        "provider": body.provider or "",
        "model": body.model,
        "base_url": body.base_url,
        "enabled": body.enabled,
    }
    # write-only api_key: if provided, store it; if absent, store empty (keep)
    if body.api_key and body.api_key != MASKED_KEY:
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
    for index, entry in enumerate(chain):
        if str(entry.get("id", index)) == provider_id:
            entry["model"] = body.model if body.model else entry.get("model", "")
            for field in ("provider", "base_url", "enabled"):
                if field in body.model_fields_set:
                    entry[field] = getattr(body, field)
            if body.api_key and body.api_key != MASKED_KEY:
                entry["api_key"] = body.api_key
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
    new_chain = [e for i, e in enumerate(chain) if str(e.get("id", i)) != provider_id]
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
    for index, entry in enumerate(chain):
        if str(entry.get("id", index)) == provider_id:
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
    for index, entry in enumerate(chain):
        if str(entry.get("id", index)) == provider_id:
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
    return {"mode": cfg.get("mode", "local_only"), "import_policy": cfg.get("import_policy", "review_first")}

@router.put("/settings/mode")
async def set_mode(body: ModeIn):
    import config
    cfg = config.load()
    cfg["mode"] = body.mode
    cfg["import_policy"] = body.import_policy
    config.save(cfg)
    return {"ok": True, "mode": body.mode, "import_policy": body.import_policy}

# ── Provider catalog, model discovery & connection testing ──────────────────

def _clamp_reliability(raw: Any) -> dict:
    base = llm.default_reliability()
    out = dict(base)
    for key, (lo, hi) in RELIABILITY_FIELDS.items():
        if key not in raw or raw[key] in (None, ""):
            continue
        try:
            out[key] = max(lo, min(hi, float(raw[key])))
        except (TypeError, ValueError):
            raise HTTPException(422, f"reliability.{key} must be a number")
    return out

def _resolve_entry(body: dict) -> tuple[dict, bool]:
    """Build a chain entry for test/discovery; resolve stored key when masked.

    Returns (entry, key_is_stored). The upstream key is resolved whenever the
    frontend sends an empty or masked api_key together with an existing id —
    raw keys are accepted from the request body only (never returned).
    """
    import config
    e = dict(body or {})
    e.setdefault("provider", "")
    stored = None
    eid = str(e.get("id") or "").strip()
    if not (e.get("api_key") or "").strip() or e.get("api_key") == MASKED_KEY:
        if eid:
            stored = next((c for c in config.load().get("chain") or []
                           if isinstance(c, dict) and str(c.get("id")) == eid), None)
    if stored:
        e["api_key"] = e.get("api_key") if e.get("api_key") == MASKED_KEY else ""
        if e["api_key"] in ("", MASKED_KEY):
            e["api_key"] = stored.get("api_key") or ""
        if not e.get("base_url"):
            e["base_url"] = stored.get("base_url") or ""
    return e, bool(stored)

@router.get("/providers/catalog")
async def get_catalog():
    import providers as prov
    return {
        "catalog": [
            {
                "id": spec.id,
                "name": spec.name,
                "protocol": spec.protocol,
                "base_url": spec.base_url,
                "requires_key": spec.requires_key,
                "requires_base_url": spec.id == "custom",
                "docs": spec.docs,
                "key_url": spec.key_url,
            }
            for spec in prov.PROVIDERS.values()
        ],
        "subscription_note": llm.SUBSCRIPTION_NOTE,
    }

@router.post("/providers/models")
async def discover_models(body: dict):
    import providers
    entry, _ = _resolve_entry(body)
    if entry.get("provider") not in providers.PROVIDERS:
        raise HTTPException(422, "unknown provider")
    models, err = await llm.fetch_models(entry)
    out = {"models": models, "count": len(models), "fetched_at": _utcnow()}
    if err:
        out["error"] = err
    return out

@router.post("/providers/test")
async def test_provider(body: dict):
    entry, _ = _resolve_entry(body)
    result = await llm.test_entry(entry)
    ok = result == "ok"
    return {"ok": ok, "message": "connected successfully" if ok else result,
            "provider": entry.get("provider") or "", "model": entry.get("model") or ""}

@router.get("/reliability")
async def get_reliability():
    stored = config.load().get("reliability") or {}
    return {"reliability": {**llm.default_reliability(), **stored},
            "descriptions": RELIABILITY_DESCRIPTIONS}

@router.put("/reliability")
async def set_reliability(body: dict):
    rel = _clamp_reliability(body)
    cfg = config.load()
    cfg["reliability"] = rel
    config.save(cfg)
    return {"ok": True, "reliability": rel}

def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

# ── Editable extraction prompt store (Part 4) ────────────────────────────────

@router.get("/prompts")
async def list_prompts():
    import services.prompts.store as store
    out = {}
    for kind in store.KINDS:
        version, custom, updated = store.load(kind)
        out[kind] = {
            "title": store.TITLES[kind],
            "purpose": store.PURPOSES[kind],
            "default_version": version,
            "customised": custom is not None,
            "updated_at": updated,
            "chart": None,  # reserved; never used (no-charts rule)
        }
    return out

@router.get("/prompts/{kind}")
async def get_prompt(kind: str):
    import services.prompts.store as store
    if kind not in store.KINDS:
        raise HTTPException(404, f"unknown prompt kind: {kind}")
    version, custom, updated = store.load(kind)
    return {
        "kind": kind,
        "title": store.TITLES[kind],
        "purpose": store.PURPOSES[kind],
        "default_version": version,
        "text": store.text(kind),
        "customised": custom is not None,
        "updated_at": updated,
        "chars": len(store.text(kind)),
    }

@router.put("/prompts/{kind}")
async def save_prompt(kind: str, body: dict):
    import services.prompts.store as store
    if kind not in store.KINDS:
        raise HTTPException(404, f"unknown prompt kind: {kind}")
    text_in = body.get("text")
    ok, err = store.save(kind, text_in)
    if not ok:
        raise HTTPException(422, err)
    version, custom, updated = store.load(kind)
    return {"ok": True, "kind": kind, "updated_at": updated,
            "default_version": version, "chars": len(custom or "")}

@router.post("/prompts/{kind}/reset")
async def reset_prompt(kind: str):
    import services.prompts.store as store
    if kind not in store.KINDS:
        raise HTTPException(404, f"unknown prompt kind: {kind}")
    store.reset(kind)
    return {"ok": True, "kind": kind, "customised": False,
            "default_version": store.DEFAULT_VERSION}