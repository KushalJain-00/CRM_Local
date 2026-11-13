# llm.py — ordered provider-failover engine for contact/EML extraction.
# The registry/protocol layer lives in providers.py; this module owns the
# execution policy: bounded retries, backoff, deadlines, JSON repair,
# failover in strict chain order, circuit breaker and diagnostics.
import asyncio
import json
import random
import re
import time

import httpx

import providers
from providers import ProviderError

PROVIDERS = list(providers.PROVIDERS)  # /api/status compat: provider id list

SUBSCRIPTION_NOTE = (
    "An API key is required for cloud providers — a ChatGPT/Claude/Gemini "
    "app subscription alone does not include API access. Ollama and custom "
    "OpenAI-compatible endpoints run locally or on your own server "
    "(LM Studio, vLLM, …) and need no key."
)

def _default_eml_prompt() -> str:
    try:
        from services.prompts.store import DEFAULT_EML_PROMPT
        return DEFAULT_EML_PROMPT
    except Exception:
        # Minimal self-contained fallback; keeps extract() usable if the
        # prompts package is unavailable.
        return ('{"name":null,"email":null,"phone_primary":null,"phone_secondary":null,'
                '"company":null,"designation":null,"address":null,"city":null,'
                '"pincode":null,"website":null}')


RETRY_BACKOFF = [1, 2]  # default per-entry sleeps (attempts = len + 1); kept for compat

TIMEOUT = 120.0  # default request timeout (local app: no proxy to race)

# Single source of truth lives in services/prompts/store.py; the fallback is
# imported lazily to avoid a hard import cycle (store imports config).
SYSTEM_PROMPT = None  # resolved to services.prompts.store.DEFAULT_EML_PROMPT in extract()

# Part 7: non-secret per-run diagnostics, one record per attempted entry.
LAST_RUN: list[dict] = []

# In-memory circuit breaker: repeated transient failures pause an entry for
# a cooldown; persistent config is never locked out (state clears on expiry).
_BREAKER_THRESHOLD = 4
_BREAKER_STATE: dict[tuple, dict] = {}
BREAKER_COOLDOWN_S = 120.0

REPAIR_USER_SUFFIX = (
    "\n--- VALIDATION FEEDBACK (your previous response was rejected) ---\n"
    "{issues}\n"
    "Return corrected instructions: ONLY a raw JSON object matching the "
    "schema above. Do not invent values you cannot see in the source."
)


def default_reliability() -> dict:
    return {
        "timeout_s": 120.0,
        "attempts": len(RETRY_BACKOFF) + 1,   # transient retries per entry
        "backoff_initial_s": RETRY_BACKOFF[0] if RETRY_BACKOFF else 1.0,
        "backoff_max_s": 16.0,
        "deadline_s": 300.0,                  # whole extract() budget
        "repair_attempts": 1,                 # invalid-JSON fix rounds per entry
        "cooldown_s": BREAKER_COOLDOWN_S,     # circuit-breaker opening window
        "fail_threshold": _BREAKER_THRESHOLD,
    }


# Reliability knob specification: bounds and human copy live with the defaults
# so the API surface is derived, never re-declared (AGENTS.md: one spec).
RELIABILITY_FIELDS = {
    "timeout_s": (5.0, 600.0),
    "attempts": (1, 6),
    "backoff_initial_s": (0.0, 60.0),
    "backoff_max_s": (0.0, 300.0),
    "deadline_s": (10.0, 1800.0),
    "repair_attempts": (0, 3),
    "cooldown_s": (0.0, 3600.0),
    "fail_threshold": (1, 50),
}

RELIABILITY_DESCRIPTIONS = {
    "timeout_s": "Seconds before a single provider request times out.",
    "attempts": "Try-again rounds per provider entry before falling over.",
    "backoff_initial_s": "Wait before the first retry (doubled per attempt).",
    "backoff_max_s": "Cap on a single retry wait.",
    "deadline_s": "Total seconds an extraction may spend across the chain.",
    "repair_attempts": "Rounds asking a provider to fix malformed JSON.",
    "cooldown_s": "How long a failing entry is paused after repeated errors.",
    "fail_threshold": "Consecutive transient failures before an entry is paused.",
}


def parse_json(raw: str) -> dict | None:
    if not raw:
        return None
    text = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        return None
    # M5: validate field lengths and formats
    field_limits = {
        "name": 100, "email": 254, "phone_primary": 30, "phone_secondary": 100,
        "company": 200, "designation": 100, "address": 500, "city": 100,
        "pincode": 20, "website": 253,
    }
    validated = {}
    for key, val in data.items():
        if key not in field_limits:
            validated[key] = val
            continue
        if val is None or (isinstance(val, str) and (not val.strip() or val.strip().lower() == "null")):
            validated[key] = None
            continue
        if not isinstance(val, str):
            val = str(val)
        val = val.strip()
        if len(val) > field_limits.get(key, 255):
            val = val[:field_limits.get(key, 255)]
        if key == "email" and val:
            if not re.match(r"^[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}$", val):
                val = None
        if key == "website" and val:
            if not re.match(r"^[a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}", val):
                val = None
        validated[key] = val
    return validated


# ── HTTP (single place; tests monkeypatch _post/_get) ────────────────────────

async def _post(url: str, headers: dict, payload: dict,
                timeout: float = TIMEOUT) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
    _raise_on_status(resp)
    return resp


async def _get(url: str, headers: dict, timeout: float = TIMEOUT / 3) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, headers=headers)
    _raise_on_status(resp)
    return resp


def _raise_on_status(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        retry_after = None
        try:
            ra = resp.headers.get("Retry-After")
            if ra:
                retry_after = min(float(ra), BREAKER_COOLDOWN_S * 10)
        except (TypeError, ValueError):
            retry_after = None
        raise providers.classify_status(resp.status_code, resp.text[:200], retry_after)


def _redact(msg: str, entry: dict) -> str:
    key = entry.get("api_key") or ""
    out = msg.replace(key, "***") if key else msg
    # Defense in depth: never echo a Bearer value even if callers mis-assemble.
    return re.sub(r"(?i)bearer\s+\S+", "bearer ***", out)


def _sleep_for(err: ProviderError, attempt: int, rel: dict) -> float:
    """Mismatched-retry guard: honour Retry-After when provided and shorter."""
    if err.retry_after is not None:
        return min(err.retry_after, rel["backoff_max_s"])
    backoff = rel["backoff_initial_s"] * (2 ** attempt)
    return min(backoff, rel["backoff_max_s"]) + random.uniform(0, 0.25)  # jitter


# ── Circuit breaker ─────────────────────────────────────────────────────────

def _breaker_key(entry: dict) -> tuple:
    return (entry.get("provider", ""), entry.get("model", ""),
            (entry.get("base_url") or "").rstrip("/"))


def breaker_blocked(entry: dict, rel: dict) -> bool:
    st = _BREAKER_STATE.get(_breaker_key(entry))
    if not st or st["failures"] < int(rel.get("fail_threshold", _BREAKER_THRESHOLD)):
        return False
    return time.time() < st["open_until"]


def _breaker_record(entry: dict, rel: dict, failed: bool) -> None:
    key = _breaker_key(entry)
    st = _BREAKER_STATE.setdefault(key, {"failures": 0, "open_until": 0.0})
    if failed:
        st["failures"] += 1
        if st["failures"] >= int(rel.get("fail_threshold", _BREAKER_THRESHOLD)):
            st["open_until"] = time.time() + float(rel.get("cooldown_s", BREAKER_COOLDOWN_S))
    else:
        _BREAKER_STATE.pop(key, None)  # success closes the breaker (auto-recovery)


def breaker_reset() -> None:
    _BREAKER_STATE.clear()


# ── Chain extraction engine ─────────────────────────────────────────────────

def entry_label(entry: dict) -> str:
    base = entry.get("base_url") or ""
    label = f"{entry.get('provider')}/{entry.get('model')}"
    if base and entry.get("provider") == "custom":
        label += f"@{base}"
    return label


async def _one_attempt(entry: dict, system: str, prompt: str, timeout: float) -> str:
    url, headers, payload = providers.build_request(entry, system, prompt)
    try:
        resp = await _post(url, headers, payload, timeout=timeout)
    except httpx.HTTPError as exc:
        raise providers.classify_network(exc)
    try:
        data = resp.json()
    except ValueError:
        raise ProviderError("output", "invalid_json",
                            "response body is not valid JSON")
    if not isinstance(data, dict):
        raise ProviderError("output", "unexpected_response",
                            "response body is not a JSON object")
    return providers.parse_response(entry, data)


async def _run_entry(entry: dict, system: str, prompt: str, rel: dict,
                     deadline: float) -> tuple[dict | None, str]:
    """Run one chain entry with bounded retries. Returns (fields, fail_reason)."""
    label = entry_label(entry)
    attempts = max(1, int(rel.get("attempts", 3)))
    for attempt in range(attempts):
        if time.time() >= deadline:
            return None, f"{label}: total deadline exceeded"
        try:
            raw = await _one_attempt(entry, system, prompt,
                                     timeout=float(rel.get("timeout_s", TIMEOUT)))
        except ProviderError as err:
            err.message = _redact(err.message, entry)
            if err.category == "permanent":
                return None, f"{label}: {err.message}"  # never retried (Part 6 @B)
            if attempt < attempts - 1:
                await asyncio.sleep(_sleep_for(err, attempt, rel))
                continue
            return None, f"{label}: {err.message} (after {attempts} attempts)"
        plain = parse_json(raw)
        if plain is not None:
            return plain, ""
        # Invalid JSON: one controlled repair attempt with explicit feedback.
        for repair in range(max(1, int(rel.get("repair_attempts", 1)))):
            if time.time() >= deadline:
                break
            repair_user = prompt + REPAIR_USER_SUFFIX.format(
                issues="previous response was not a parseable JSON object with the required schema")
            try:
                raw2 = await _one_attempt(entry, system, repair_user,
                                          timeout=float(rel.get("timeout_s", TIMEOUT)))
            except ProviderError as err:
                err.message = _redact(err.message, entry)
                if err.category == "permanent":
                    break
                continue  # transient repair failure: try the repair once more
            fixed = parse_json(raw2)
            if fixed is not None:
                return fixed, ""
        return None, f"{label}: invalid or unusable JSON (repair attempted)"
    return None, f"{label}: exhausted retries"


async def extract(chain: list, prompt: str, *, system: str | None = None,
                  reliability: dict | None = None) -> tuple[dict | None, str]:
    """Try each enabled entry in order. Returns (fields, provider_label_or_error)."""
    global LAST_RUN
    LAST_RUN = []
    system = system if system is not None else _default_eml_prompt()
    rel = {**default_reliability(), **(reliability or {})}
    entries = [e for e in chain if isinstance(e, dict) and e.get("enabled", True)]
    if not entries:
        return None, "no provider configured"
    deadline = time.time() + float(rel.get("deadline_s", 300.0))
    failures = []  # one redacted line per entry tried, in chain order
    for entry in entries:
        label = entry_label(entry)
        rec = {"provider": label, "attempts": 0, "fewer_skipped": False,
               "category": None, "reason": None}
        if breaker_blocked(entry, rel):
            rec.update(category="transient",
                       reason="circuit breaker open (recent failures)")
            LAST_RUN.append(rec)
            continue
        try:
            fields, reason = await _run_entry(entry, system, prompt, rel, deadline)
        except Exception as exc:  # one broken entry must never stop the chain
            reason = f"{label}: {_redact(str(exc), entry)}"
            fields = None
        if fields is not None:
            _breaker_record(entry, rel, failed=False)
            rec.update(attempts=1, category=None, reason=None)
            LAST_RUN.append(rec)
            return fields, reason or label  # reason="" on success → use label
        rec.update(category="failure", reason=reason)
        LAST_RUN.append(rec)
        _breaker_record(entry, rel, failed=True)
        failures.append(reason)
    return None, "; ".join(failures) or "unspecified extraction failure"


def describe_failure(kind: str, chain: list, reliability: dict | None = None) -> str:
    """Part 6 @F: aggregate, human-readable failure report (no keys)."""
    tries = [r for r in LAST_RUN]
    line = f"all {len(tries)} provider entries failed for {kind} extraction"
    for r in tries:
        line += f"; {r['provider']}: {r['reason']}"
    return line


async def test_entry(entry: dict) -> str:
    """Real single-request connectivity test for the Settings Test button."""
    provider = entry.get("provider", "")
    try:
        spec = providers.get_spec(provider)
    except ProviderError:
        return f"Unknown provider: {provider}"
    rel = default_reliability()
    if not entry.get("model"):
        return "Select a model first."
    url, headers, payload = providers.build_request(entry, "Reply with JSON only.",
                                                    'Return {"ok": true} and nothing else.')
    try:
        resp = await _post(url, headers, payload, timeout=float(rel["timeout_s"]))
        data = resp.json()
    except ProviderError as err:
        return _redact(err.message, entry)
    except ValueError:
        return "Reply was not valid JSON."
    except Exception as exc:
        return _redact(providers.classify_network(exc).message, entry)
    try:
        text = providers.parse_response(entry, data)
    except ProviderError as err:
        return _redact(err.message, entry)
    if parse_json(text) is None:
        return "replied, but not valid JSON"
    return "ok"


# ── Model discovery helper (used by the settings API) ────────────────────────

async def fetch_models(entry: dict) -> tuple[list[str], str]:
    """(models, error). Resolves a listing endpoint via the provider spec."""
    try:
        spec = providers.PROVIDERS.get(entry.get("provider") or "")
        if spec is None:
            return [], "unknown provider"
        if spec.requires_key and not (entry.get("api_key") or "").strip():
            return [], "an API key is required to list models"
        url = providers.models_url(entry)
        headers = providers.headers_of(entry)
        resp = await _get(url, headers)
        return providers.parse_models(entry, resp.json()), ""
    except ProviderError as err:
        return [], _redact(err.message, entry)
    except Exception as exc:
        return [], _redact(providers.classify_network(exc).message, entry)
