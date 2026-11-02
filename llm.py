# llm.py — ordered provider failover for contact extraction.
# Cloud APIs are primary; ollama is just another chain entry the user can add.
import asyncio
import json
import re

import httpx

RETRY_BACKOFF = [1, 2]  # attempts per entry = len + 1
TIMEOUT = 120.0  # local app: no Cloudflare proxy to race

SYSTEM_PROMPT = """You extract one contact and company location from an email signature/header/body.
Return ONLY a raw JSON object (no markdown) with EXACTLY these keys; use null if unknown:
{"name":null,"email":null,"phone_primary":null,"phone_secondary":null,"company":null,"designation":null,"address":null,"city":null,"pincode":null,"website":null}
Rules: Always extract the company's location/destination/city/address mentioned in the signature or email (look for Plant, Works, Factory, Office, Branch, City, State, or Industrial Estate/GIDC). Never invent values."""

URLS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
}

PROVIDERS = ["openrouter", "groq", "gemini", "openai", "deepseek", "anthropic", "ollama"]


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
    return data if isinstance(data, dict) else None


async def _call(entry: dict, system: str, user: str) -> str:
    provider = entry.get("provider", "")
    model = entry.get("model", "")
    key = entry.get("api_key", "")
    headers = {"Content-Type": "application/json"}

    if provider == "ollama":
        base = (entry.get("base_url") or "http://localhost:11434").rstrip("/")
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
        resp = await _post(f"{base}/api/chat", headers, payload)
        return resp.json().get("message", {}).get("content", "")

    if provider == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers["x-goog-api-key"] = key
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
        }
        resp = await _post(url, headers, payload)
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    if provider == "anthropic":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        payload = {
            "model": model, "max_tokens": 2048, "temperature": 0.1,
            "system": system, "messages": [{"role": "user", "content": user}],
        }
        resp = await _post(URLS[provider], headers, payload)
        return resp.json()["content"][0]["text"].strip()

    if provider not in URLS:
        raise ValueError(f"unknown provider: {provider}")

    headers["Authorization"] = f"Bearer {key}"
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://crm.local"
        headers["X-Title"] = "CRM Local"
    payload = {
        "model": model, "temperature": 0.1, "max_tokens": 2048,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if provider in ("openai", "groq", "deepseek"):
        payload["response_format"] = {"type": "json_object"}
    resp = await _post(URLS[provider], headers, payload)
    return resp.json()["choices"][0]["message"]["content"].strip()


async def _post(url: str, headers: dict, payload: dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp


def _redact(msg: str, entry: dict) -> str:
    key = entry.get("api_key") or ""
    return msg.replace(key, "***") if key else msg


async def extract(chain: list, prompt: str) -> tuple[dict | None, str]:
    """Try each enabled entry in order. Returns (fields, provider_label_or_error)."""
    entries = [e for e in chain if e.get("enabled", True)]
    if not entries:
        return None, "no provider configured"
    last_err = "chain empty"
    for entry in entries:
        label = f"{entry.get('provider')}/{entry.get('model')}"
        for attempt in range(len(RETRY_BACKOFF) + 1):
            try:
                raw = await _call(entry, SYSTEM_PROMPT, prompt)
                data = parse_json(raw)
                if data is not None:
                    return data, label
                last_err = f"{label}: invalid JSON"
            except Exception as exc:  # one bad provider must not stop the chain
                last_err = f"{label}: {_redact(str(exc), entry)}"
            if attempt < len(RETRY_BACKOFF):
                await asyncio.sleep(RETRY_BACKOFF[attempt])
    return None, last_err


async def test_entry(entry: dict) -> str:
    """Returns 'ok' or an error string, for the Settings Test button."""
    try:
        raw = await _call(entry, "Reply with JSON only.",
                          'Return {"ok": true} and nothing else.')
        return "ok" if parse_json(raw) is not None else "replied, but not valid JSON"
    except Exception as exc:
        return _redact(str(exc), entry)
