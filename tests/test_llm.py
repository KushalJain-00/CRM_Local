import asyncio

import llm


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def test_parse_json_strips_code_fences():
    assert llm.parse_json('```json\n{"name":"A"}\n```') == {"name": "A"}
    assert llm.parse_json("no json here") is None


def test_chain_fails_over_to_next_provider(monkeypatch):
    calls = []

    async def fake_post(url, headers, payload):
        calls.append(url)
        if "openrouter" in url:
            raise RuntimeError("HTTP 429: rate limited")
        return FakeResponse({"choices": [{"message": {"content": '{"name":"Asha"}'}}]})

    monkeypatch.setattr(llm, "_post", fake_post)
    monkeypatch.setattr(llm, "RETRY_BACKOFF", [])

    chain = [
        {"provider": "openrouter", "model": "m1", "api_key": "k1", "enabled": True},
        {"provider": "groq", "model": "m2", "api_key": "k2", "enabled": True},
    ]
    fields, label = asyncio.run(llm.extract(chain, "prompt"))
    assert fields == {"name": "Asha"}
    assert label == "groq/m2"
    assert len(calls) == 2


def test_disabled_entries_are_skipped(monkeypatch):
    async def fake_post(url, headers, payload):
        return FakeResponse({"choices": [{"message": {"content": '{"name":"X"}'}}]})

    monkeypatch.setattr(llm, "_post", fake_post)
    chain = [
        {"provider": "openrouter", "model": "m1", "api_key": "k1", "enabled": False},
        {"provider": "groq", "model": "m2", "api_key": "k2", "enabled": True},
    ]
    fields, label = asyncio.run(llm.extract(chain, "prompt"))
    assert fields == {"name": "X"}
    assert label == "groq/m2"


def test_empty_chain_reports_local_only():
    fields, label = asyncio.run(llm.extract([], "prompt"))
    assert fields is None
    assert label == "no provider configured"


def test_ollama_uses_local_chat_endpoint(monkeypatch):
    seen = {}

    async def fake_post(url, headers, payload):
        seen["url"] = url
        seen["payload"] = payload
        return FakeResponse({"message": {"content": '{"name":"Local"}'}})

    monkeypatch.setattr(llm, "_post", fake_post)
    chain = [{"provider": "ollama", "model": "llama3", "base_url": "http://localhost:11434/",
              "enabled": True}]
    fields, _ = asyncio.run(llm.extract(chain, "prompt"))
    assert fields == {"name": "Local"}
    assert seen["url"] == "http://localhost:11434/api/chat"
    assert seen["payload"]["format"] == "json"
