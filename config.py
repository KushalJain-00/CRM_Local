# config.py — local settings + data location. No cloud, no accounts.
import json
import os
from pathlib import Path

APP_NAME = "CRM_Local"

DEFAULTS = {
    "crm_dir": "",
    "eml_dir": "",
    # Ordered failover chain. Empty = local regex extraction only.
    # Entry: {provider, model, api_key, base_url, enabled}
    "chain": [],
    "watch": False,
    "watch_interval": 30,
    "autostart": False,
    "theme": "light",
    # Reliability knobs: spec (defaults+bounds+copy) lives in llm.py beside
    # default_reliability(); api/settings.py clamps against it. Prompts are
    # edited only via /api/prompts.
    "reliability": {},
    "prompts": {},
}


def _default_data_dir() -> Path:
    """Where the app lives by default. Used by data_dir() and by the
    migration-gate anchor, which must NOT follow config.data_dir()
    monkeypatching (a stray redirect must never point the D-030 gate at
    the wrong file). No mkdir — callers decide."""
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
    return Path.home() / ".crm_local"


def data_dir() -> Path:
    d = _default_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def canonical_db_path() -> Path:
    """Canonical production DB path (D-030 gate anchor). Ignores any
    monkeypatched data_dir; never creates directories."""
    return _default_data_dir() / "crm.db"


def config_path() -> Path:
    return data_dir() / "config.json"


def db_path(which: str) -> Path:
    if which not in ("crm", "eml"):
        raise ValueError(f"unknown db: {which}")
    return data_dir() / f"{which}.db"


def load() -> dict:
    p = config_path()
    cfg = dict(DEFAULTS)
    if p.exists():
        try:
            data = json.loads(p.read_text("utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
        except Exception:
            # A corrupt config must not brick the app; fall back to defaults.
            pass
    if not isinstance(cfg.get("chain"), list):
        cfg["chain"] = []
    return cfg


def _private(p: Path) -> None:
    # SEC-09: config.json holds provider keys — owner-only on POSIX.
    # Windows inherits the profile ACL; os.chmod there is a no-op for modes.
    if os.name == "nt":
        return
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def lock_down() -> None:
    """Force config.json to 0600 on app startup (SEC-09)."""
    p = config_path()
    if p.exists():
        _private(p)


def save(cfg: dict) -> None:
    p = config_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2), "utf-8")
    _private(tmp)  # chmod before replace so the file is never world-readable
    os.replace(tmp, p)
    _private(p)
