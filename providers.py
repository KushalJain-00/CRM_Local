# providers.py — provider registry, request/parse per protocol, error classes,
# model discovery. Provider-specific protocols live here only (Part 2); the
# chain engine and extraction logic stay in llm.py.
"""
Each entry in PROVIDERS describes one provider: display name, protocol,
default base URL, auth style and how to list models. `custom` is the generic
OpenAI-compatible adapter for any base URL (LM Studio, vLLM, Mistral, xAI,
Together, Fireworks, Cerebras, Perplexity, open-source gateways).

HTTP is done by the caller (llm._post / llm._get) so tests can mock a single
place and tests never need network access.
"""
from dataclasses import dataclass

# ── Error taxonomy (Part 6 @A) ───────────────────────────────────────────────

# HTTP statuses that are transient by provider convention.
TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}


class ProviderError(Exception):
    """Structured provider failure. `category`: transient|permanent|output."""

    def __init__(self, category: str, code: str, message: str,
                 retry_after: float | None = None):
        super().__init__(message)
        self.category = category
        self.code = code
        self.message = message
        self.retry_after = retry_after


def classify_status(status: int, body: str = "",
                    retry_after: float | None = None) -> ProviderError:
    friendly = {
        400: "invalid request",
        401: "invalid or missing API key",
        403: "access denied",
        404: "invalid endpoint or model",
        408: "request timeout",
        425: "too early",
        429: "rate limited",
        500: "server error",
        502: "upstream error",
        503: "service unavailable",
        504: "gateway timeout",
    }
    if status in TRANSIENT_STATUS:
        return ProviderError("transient", f"HTTP {status}",
                             friendly.get(status, f"HTTP {status}"),
                             retry_after=retry_after)
    msg = friendly.get(status, f"unexpected HTTP {status}")
    text = (body or "")[:200].strip()
    if text:
        msg += f" — {text}"
    return ProviderError("permanent", f"HTTP {status}", msg)


def classify_network(exc: Exception) -> ProviderError:
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return ProviderError("transient", "timeout", "connection timed out")
    if "ssl" in name:
        return ProviderError("permanent", "ssl_error", f"TLS failure: {exc}")
    return ProviderError("transient", "network",
                         f"connection failure: {type(exc).__name__}")


# ── Registry ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProviderSpec:
    id: str
    name: str
    protocol: str          # openai | anthropic | gemini | ollama
    base_url: str
    auth: str              # bearer | x-api-key | x-goog-api-key | none
    requires_key: bool
    json_mode: bool        # response_format: json_object where supported
    docs: str = ""
    key_url: str = ""      # where API access is documented (not a subscription)


PROVIDERS = {
    "openai": ProviderSpec(
        id="openai", name="OpenAI", protocol="openai",
        base_url="https://api.openai.com/v1", auth="bearer",
        requires_key=True, json_mode=True,
        docs="https://platform.openai.com/docs", key_url="https://platform.openai.com/api-keys",
    ),
    "openrouter": ProviderSpec(
        id="openrouter", name="OpenRouter", protocol="openai",
        base_url="https://openrouter.ai/api/v1", auth="bearer",
        requires_key=True, json_mode=False,
        docs="https://openrouter.ai/docs", key_url="https://openrouter.ai/settings/keys",
    ),
    "groq": ProviderSpec(
        id="groq", name="Groq", protocol="openai",
        base_url="https://api.groq.com/openai/v1", auth="bearer",
        requires_key=True, json_mode=True,
        docs="https://console.groq.com/docs", key_url="https://console.groq.com/keys",
    ),
    "gemini": ProviderSpec(
        id="gemini", name="Google Gemini", protocol="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta", auth="x-goog-api-key",
        requires_key=True, json_mode=False,
        docs="https://ai.google.dev/gemini-api/docs", key_url="https://aistudio.google.com/apikey",
    ),
    "anthropic": ProviderSpec(
        id="anthropic", name="Anthropic Claude", protocol="anthropic",
        base_url="https://api.anthropic.com/v1", auth="x-api-key",
        requires_key=True, json_mode=False,
        docs="https://docs.anthropic.com", key_url="https://console.anthropic.com/settings/keys",
    ),
    "deepseek": ProviderSpec(
        id="deepseek", name="DeepSeek", protocol="openai",
        base_url="https://api.deepseek.com", auth="bearer",
        requires_key=True, json_mode=True,
        docs="https://api-docs.deepseek.com", key_url="https://platform.deepseek.com/api_keys",
    ),
    "ollama": ProviderSpec(
        id="ollama", name="Ollama (local)", protocol="ollama",
        base_url="http://localhost:11434", auth="none",
        requires_key=False, json_mode=True,
        docs="https://github.com/ollama/ollama",
    ),
    "custom": ProviderSpec(
        id="custom", name="Custom OpenAI-compatible", protocol="openai",
        base_url="", auth="bearer",
        requires_key=True, json_mode=True,
        docs="https://platform.openai.com/docs/api-reference",
    ),
}

# Anthropic message API version (single source, matches existing llm.py).
ANTHROPIC_VERSION = "2023-06-01"


def get_spec(provider: str) -> ProviderSpec:
    if provider not in PROVIDERS:
        raise ProviderError(
            "permanent", "unknown_provider", f"unknown provider: {provider}")
    return PROVIDERS[provider]


def base_url_of(entry: dict, spec: ProviderSpec | None = None) -> str:
    """Base URL for a chain entry, honoring the optional custom override."""
    spec = spec or get_spec(entry.get("provider", ""))
    base = (entry.get("base_url") or spec.base_url).rstrip("/")
    if spec.id == "custom" and not entry.get("base_url"):
        raise ProviderError(
            "permanent", "missing_base_url",
            "custom provider needs a base URL (e.g. http://localhost:1234/v1)")
    if entry.get("provider") == "ollama" and not entry.get("base_url"):
        pass  # spec default already covers it (http://localhost:11434)
    return base


def headers_of(entry: dict, spec: ProviderSpec | None = None) -> dict:
    spec = spec or get_spec(entry.get("provider", ""))
    key = entry.get("api_key") or ""
    if spec.auth == "bearer":
        h = {"Authorization": f"Bearer {key}"}
        if spec.id == "openrouter":
            h["HTTP-Referer"] = "https://crm.local"
            h["X-Title"] = "CRM Local"
        return h
    if spec.auth == "x-api-key":
        return {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    if spec.auth == "x-goog-api-key":
        return {"x-goog-api-key": key}
    return {}


def chat_url(base: str, spec: ProviderSpec, model: str) -> str:
    if spec.protocol == "gemini":
        return f"{base}/models/{model}:generateContent"
    if spec.protocol == "ollama":
        return f"{base}/api/chat"
    if spec.protocol == "anthropic":
        return f"{base}/messages"
    return f"{base}/chat/completions"


def build_request(entry: dict, system: str, user: str) -> tuple[str, dict, dict]:
    """(url, headers, payload) for one chat completion. Pure — no HTTP here."""
    spec = get_spec(entry.get("provider", ""))
    base = base_url_of(entry, spec)
    model = (entry.get("model") or "").strip()
    if not model:
        raise ProviderError("permanent", "missing_model",
                            f"{spec.name}: no model selected")
    if spec.id == "gemini" and not _MODEL_NAME_OK.match(model):
        raise ProviderError("permanent", "invalid_model_name",
                            f"gemini: invalid model name: {model[:50]}")
    if spec.protocol == "ollama":
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
    elif spec.protocol == "gemini":
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
        }
    elif spec.protocol == "anthropic":
        payload = {
            "model": model, "max_tokens": 2048, "temperature": 0.1,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
    else:  # openai-compatible
        payload = {
            "model": model, "temperature": 0.1, "max_tokens": 2048,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        if spec.json_mode:
            payload["response_format"] = {"type": "json_object"}
    return chat_url(base, spec, model), headers_of(entry, spec), payload


_MODEL_NAME_OK = __import__("re").compile(r"^[a-zA-Z0-9._-]+$")


def parse_response(entry: dict, data: dict) -> str:
    """Model text from a successful provider JSON body. Raises output errors."""
    spec = get_spec(entry.get("provider", ""))
    try:
        if spec.protocol == "ollama":
            text = data["message"]["content"]
        elif spec.protocol == "gemini":
            candidates = data.get("candidates") or []
            if not candidates:
                block = (data.get("promptFeedback") or {}).get("blockReason")
                raise ProviderError(
                    "output", "provider_refused",
                    f"model returned no candidates{f' (blocked: {block})' if block else ''}")
            text = candidates[0]["content"]["parts"][0]["text"]
        elif spec.protocol == "anthropic":
            text = data["content"][0]["text"]
        else:
            text = data["choices"][0]["message"]["content"]
    except (ProviderError):
        raise
    except (KeyError, IndexError, TypeError):
        raise ProviderError("output", "unexpected_response",
                            "response body did not match the provider schema")
    if not isinstance(text, str) or not text.strip():
        raise ProviderError("output", "empty_response", "model returned empty text")
    return text.strip()


# ── Model discovery (Part 2) ────────────────────────────────────────────────

def models_url(entry: dict, spec: ProviderSpec | None = None) -> str:
    spec = spec or get_spec(entry.get("provider", ""))
    base = base_url_of(entry, spec)
    if spec.protocol == "ollama":
        return f"{base}/api/tags"
    return f"{base}/models"


def parse_models(entry: dict, data: dict) -> list[str]:
    """Model ids from a successful listing endpoint."""
    spec = get_spec(entry.get("provider", ""))
    ids: list[str] = []
    if spec.protocol == "ollama":
        ids = [m.get("name") or m.get("model") or "" for m in data.get("models", [])]
    elif spec.protocol == "gemini":
        for m in data.get("models", []):
            methods = m.get("supportedGenerationMethods") or []
            if methods and "generateContent" not in methods:
                continue  # embedding/aista-only models can't chat
            name = m.get("name") or ""          # "models/gemini-1.5-pro"
            ids.append(name.split("models/", 1)[-1])
    else:
        items = data.get("data") if isinstance(data.get("data"), list) else data.get("models")
        if isinstance(items, list):
            ids = [m.get("id") or m.get("name") or "" for m in items
                   if isinstance(m, dict)]
    return sorted({i for i in ids if i})
