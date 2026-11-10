# tests/test_llm_failover.py — engine policy: order, retries, failover,
# deadlines, repair, breaker, aggregate errors. All HTTP is faked at llm._post;
# sleeps are stubbed so tests are fast and deterministic.
import asyncio
import itertools
import time

import pytest

import llm


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)
        self.headers = {}

    def json(self):
        return self._payload


def _no_sleep(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return sleeps


def _ok(content):
    return FakeResponse({"choices": [{"message": {"content": content}}]})


def _chain(*spec):
    return [dict(provider=p.split("/", 1)[0], model=p.split("/", 1)[1],
                 api_key=f"k-{p}", enabled=True)
            for p in spec]


@pytest.fixture(autouse=True)
def _breaker_clean():
    llm.breaker_reset()
    yield
    llm.breaker_reset()


def test_order_follows_chain_not_registry(monkeypatch):
    seen = []

    async def fake_post(url, headers, payload, timeout=None):
        seen.append(url)
        return _ok('{"name":"A"}')

    monkeypatch.setattr(llm, "_post", fake_post)
    fields, label = asyncio.run(
        llm.extract(_chain("groq/m1", "openai/m2"), "p"))
    assert fields["name"] == "A"
    assert label == "groq/m1"
    assert "api.groq.com" in seen[0]


def test_disabled_entries_never_called(monkeypatch):
    chain = [
        {"provider": "openai", "model": "m", "api_key": "k", "enabled": False},
        {"provider": "groq", "model": "m", "api_key": "k", "enabled": True},
    ]

    async def fake_post(url, headers, payload, timeout=None):
        assert "api.groq.com" in url
        return _ok('{"name":"X"}')

    monkeypatch.setattr(llm, "_post", fake_post)
    _, label = asyncio.run(llm.extract(chain, "p"))
    assert label == "groq/m"


def test_permanent_401_moves_on_without_retry(monkeypatch):
    calls: list[str] = []

    async def fake_post(url, headers, payload, timeout=None):
        calls.append(url)
        if "api.openai.com" in url:
            raise llm.ProviderError("permanent", "HTTP 401", "invalid or missing API key")
        return _ok('{"name":"B"}')

    monkeypatch.setattr(llm, "_post", fake_post)
    sleeps = _no_sleep(monkeypatch)
    fields, label = asyncio.run(
        llm.extract(_chain("openai/m", "groq/m"), "p"))
    assert fields == {"name": "B"} and label == "groq/m"
    assert len(calls) == 2          # one request per entry — no 401 retries
    assert sleeps == []


def test_transient_500_retries_then_fails_over(monkeypatch):
    calls: list[str] = []

    async def fake_post(url, headers, payload, timeout=None):
        calls.append(url)
        if "api.openai.com" in url:
            raise llm.ProviderError("transient", "HTTP 500", "server error")
        return _ok('{"name":"C"}')

    monkeypatch.setattr(llm, "_post", fake_post)
    sleeps = _no_sleep(monkeypatch)
    fields, label = asyncio.run(
        llm.extract(_chain("openai/m", "groq/m"), "p"))
    assert fields == {"name": "C"}
    assert len(calls) == 4          # 3 attempts openai + 1 groq success
    assert sleeps and [s > 0 for s in sleeps] == [True] * len(sleeps)


def test_retry_after_is_shorter_than_backoff(monkeypatch):
    async def fake_post(url, headers, payload, timeout=None):
        raise llm.ProviderError("transient", "HTTP 429", "rate limited",
                                retry_after=0.5)

    monkeypatch.setattr(llm, "_post", fake_post)
    sleeps = _no_sleep(monkeypatch)
    asyncio.run(llm.extract(_chain("openai/m"), "p"))
    assert sleeps and all(s <= 0.5 + 0.25 for s in sleeps)


def test_json_repair_recovers_once(monkeypatch):
    prompts = []

    async def fake_post(url, headers, payload, timeout=None):
        prompts.append(payload["messages"][1]["content"])
        if len(prompts) == 1:
            return _ok("not json at all")
        return _ok('{"name":"Fixed"}')

    monkeypatch.setattr(llm, "_post", fake_post)
    fields, label = asyncio.run(llm.extract(_chain("openai/m"), "p"))
    assert fields == {"name": "Fixed"}
    assert "VALIDATION FEEDBACK" in prompts[1]


def test_unrepairable_json_fails_over_to_next_entry(monkeypatch):
    attempts = []

    async def fake_post(url, headers, payload, timeout=None):
        attempts.append(url)
        return _ok("still not json")

    monkeypatch.setattr(llm, "_post", fake_post)
    fields, label = asyncio.run(llm.extract(_chain("openai/m", "groq/m"), "p"))
    assert fields is None
    # repair attempted on openai, then failover; groq also tries + repair
    assert len(attempts) == 4
    assert "invalid or unusable JSON" in label


def test_same_provider_two_models_in_order(monkeypatch):
    seen_models = []

    async def fake_post(url, headers, payload, timeout=None):
        seen_models.append(payload["model"])
        raise llm.ProviderError("permanent", "HTTP 404", "invalid endpoint or model")

    monkeypatch.setattr(llm, "_post", fake_post)
    chain = _chain("openai/model-a", "openai/model-b")
    chain[1]["model"] = "model-b"
    fields, label = asyncio.run(llm.extract(chain, "p"))
    assert seen_models == ["model-a", "model-b"]
    assert fields is None


def test_total_deadline_stops_the_chain(monkeypatch):
    async def fake_post(url, headers, payload, timeout=None):
        raise llm.ProviderError("transient", "HTTP 503", "service unavailable")

    monkeypatch.setattr(llm, "_post", fake_post)
    _no_sleep(monkeypatch)
    orig_clock = time.time  # time is monkeypatched on llm.time module; capture first
    tick = itertools.count(1)  # the clock jumps an hour per call: deadline gone
    monkeypatch.setattr(llm.time, "time",
                        lambda: orig_clock() + next(tick) * 3600.0)
    fields, label = asyncio.run(
        llm.extract(_chain("openai/m", "groq/m"), "p"))
    assert fields is None
    assert "deadline" in label


def test_circuit_breaker_skips_repeatedly_failing_entry(monkeypatch):
    calls: list[str] = []

    async def fake_post(url, headers, payload, timeout=None):
        calls.append(url)
        raise llm.ProviderError("transient", "HTTP 503", "service unavailable")

    monkeypatch.setattr(llm, "_post", fake_post)
    rel = llm.default_reliability()
    rel.update(fail_threshold=2, cooldown_s=120.0)
    _no_sleep(monkeypatch)
    for _ in range(2):
        asyncio.run(llm.extract(_chain("openai/m"), "p", reliability=dict(rel)))
    before = len(calls)
    fields, label = asyncio.run(llm.extract(_chain("openai/m"), "p", reliability=dict(rel)))
    assert fields is None
    assert len(calls) == before  # breaker open: no new request happened
    assert "circuit breaker" in llm.LAST_RUN[0]["reason"]


def test_success_resets_breaker(monkeypatch):
    async def fake_post(url, headers, payload, timeout=None):
        return _ok('{"name":"OK"}')

    monkeypatch.setattr(llm, "_post", fake_post)
    rel = llm.default_reliability()
    rel["fail_threshold"] = 2
    asyncio.run(llm.extract(_chain("openai/m"), "p", reliability=dict(rel)))
    assert not llm.breaker_blocked(_chain("openai/m")[0], rel)


def test_aggregate_error_lists_every_entry_without_leaking_keys(monkeypatch):
    async def fake_post(url, headers, payload, timeout=None):
        raise llm.ProviderError("permanent", "HTTP 401", "invalid or missing API key")
    monkeypatch.setattr(llm, "_post", fake_post)
    fields, label = asyncio.run(llm.extract(_chain("openai/m", "groq/m"), "p"))
    assert fields is None
    assert "openai/m" in label and "groq/m" in label
    assert "k-openai" not in label and "k-groq" not in label


def test_diagnostics_recorded_per_entry(monkeypatch):
    async def fake_post(url, headers, payload, timeout=None):
        if "api.openai.com" in url:
            raise llm.ProviderError("permanent", "HTTP 403", "access denied")
        return _ok('{"name":"D"}')

    monkeypatch.setattr(llm, "_post", fake_post)
    asyncio.run(llm.extract(_chain("openai/m", "groq/m"), "p"))
    assert [r["provider"] for r in llm.LAST_RUN] == ["openai/m", "groq/m"]
    assert llm.LAST_RUN[0]["reason"] and llm.LAST_RUN[1]["reason"] is None


def test_test_entry_reports_ok_and_errors(monkeypatch):
    async def ok_post(url, headers, payload, timeout=None):
        return _ok('{"ok": true}')

    monkeypatch.setattr(llm, "_post", ok_post)
    assert asyncio.run(llm.test_entry(_chain("openai/m")[0])) == "ok"

    async def bad_post(url, headers, payload, timeout=None):
        raise llm.ProviderError("permanent", "HTTP 401", "invalid or missing API key")
    monkeypatch.setattr(llm, "_post", bad_post)
    msg = asyncio.run(llm.test_entry(_chain("openai/m")[0]))
    assert "API key" in msg and "sk-x" not in msg


def test_test_entry_requires_model():
    msg = asyncio.run(llm.test_entry({"provider": "openai", "model": ""}))
    assert "model" in msg.lower()


def test_model_discovery_via_mono(monkeypatch):
    seen = []

    async def fake_get(url, headers, timeout=None):
        seen.append(url)
        return FakeResponse({"data": [{"id": "z"}, {"id": "a"}]})

    monkeypatch.setattr(llm, "_get", fake_get)
    models, err = asyncio.run(llm.fetch_models(_chain("openai/m")[0]))
    assert models == ["a", "z"] and err == ""
    assert "api.openai.com/v1/models" in seen[0]


def test_discovery_requires_key_before_calling_network(monkeypatch):
    calls = []

    async def fake_get(url, headers, timeout=None):
        calls.append(url)
        return FakeResponse({"data": [{"id": "m"}]})

    monkeypatch.setattr(llm, "_get", fake_get)
    models, err = asyncio.run(llm.fetch_models({"provider": "openai", "api_key": "  "}))
    assert models == [] and "API key is required" in err
    assert calls == []  # no network round-trip without credentials


def test_ollama_discovery_needs_no_key(monkeypatch):
    seen = []

    async def fake_get(url, headers, timeout=None):
        seen.append(url)
        return FakeResponse({"models": [{"name": "llama3"}, {"name": "qwen2"}]})

    monkeypatch.setattr(llm, "_get", fake_get)
    models, err = asyncio.run(llm.fetch_models(_chain("ollama/m")[0]))
    assert models == ["llama3", "qwen2"]
    assert "api/tags" in seen[0]


def test_discovery_failure_returns_error_string(monkeypatch):
    async def fake_get(url, headers, timeout=None):
        raise llm.ProviderError("permanent", "HTTP 401", "invalid or missing API key")

    monkeypatch.setattr(llm, "_get", fake_get)
    models, err = asyncio.run(llm.fetch_models(_chain("openai/m")[0]))
    assert models == [] and "API key" in err
