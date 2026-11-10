# tests/test_providers.py — registry, request build/parse, discovery, errors.
import providers


def test_registry_has_required_providers():
    for pid in ("openai", "openrouter", "groq", "gemini", "anthropic",
                "deepseek", "ollama", "custom"):
        assert pid in providers.PROVIDERS, pid


def test_unknown_provider_raises_permanent():
    err = providers.get_spec("not-a-provider") if False else None
    try:
        providers.get_spec("not-a-provider")
    except providers.ProviderError as e:
        assert e.category == "permanent"
    else:
        assert False, "expected ProviderError"


def test_openai_request_shape():
    entry = {"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-x"}
    url, headers, payload = providers.build_request(entry, "SYS", "USR")
    assert url == "https://api.openai.com/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-x"
    assert payload["messages"][0] == {"role": "system", "content": "SYS"}
    assert payload["response_format"] == {"type": "json_object"}


def test_openrouter_request_carries_referer_headers():
    entry = {"provider": "openrouter", "model": "m", "api_key": "k"}
    _, headers, payload = providers.build_request(entry, "S", "U")
    assert headers["HTTP-Referer"] == "https://crm.local"
    assert "response_format" not in payload


def test_gemini_request_shape_and_model_guard():
    entry = {"provider": "gemini", "model": "gemini-1.5-pro", "api_key": "key"}
    url, headers, payload = providers.build_request(entry, "SYS", "USR")
    assert url == ("https://generativelanguage.googleapis.com/v1beta/"
                   "models/gemini-1.5-pro:generateContent")
    assert headers["x-goog-api-key"] == "key"
    assert payload["system_instruction"]["parts"][0]["text"] == "SYS"
    bad = dict(entry, model="../etc")
    try:
        providers.build_request(bad, "S", "U")
    except providers.ProviderError as e:
        assert e.category == "permanent"
    else:
        assert False


def test_anthropic_request_shape():
    entry = {"provider": "anthropic", "model": "claude-x", "api_key": "k"}
    url, headers, payload = providers.build_request(entry, "S", "U")
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "k"
    assert headers["anthropic-version"] == providers.ANTHROPIC_VERSION
    assert payload["system"] == "S"


def test_ollama_request_shape_and_default_base():
    entry = {"provider": "ollama", "model": "llama3"}
    url, headers, payload = providers.build_request(entry, "S", "U")
    assert url == "http://localhost:11434/api/chat"
    assert payload["format"] == "json"
    assert headers == {}


def test_custom_base_url_required():
    try:
        providers.build_request({"provider": "custom", "model": "m", "api_key": "k"}, "S", "U")
    except providers.ProviderError as e:
        assert e.category == "permanent" and "base URL" in e.message
    else:
        assert False
    url, _, _ = providers.build_request(
        {"provider": "custom", "model": "m", "api_key": "k",
         "base_url": "http://localhost:1234/v1"}, "S", "U")
    assert url == "http://localhost:1234/v1/chat/completions"


def test_missing_model_is_permanent():
    try:
        providers.build_request({"provider": "openai", "model": " "}, "S", "U")
    except providers.ProviderError as e:
        assert e.category == "permanent"
    else:
        assert False


def test_parse_response_per_protocol():
    ok = providers.parse_response(
        {"provider": "openai"}, {"choices": [{"message": {"content": " hi "}}]})
    assert ok == "hi"
    assert providers.parse_response(
        {"provider": "anthropic"}, {"content": [{"text": "hey"}]}) == "hey"
    assert providers.parse_response(
        {"provider": "ollama"}, {"message": {"content": "x"}}) == "x"
    assert providers.parse_response(
        {"provider": "gemini"},
        {"candidates": [{"content": {"parts": [{"text": "g"}]}}]}) == "g"


def test_parse_response_output_errors():
    for entry, body in [
        ({"provider": "openai"}, {"choices": []}),
        ({"provider": "ollama"}, {"unexpected": 1}),
        ({"provider": "gemini"}, {"promptFeedback": {"blockReason": "SAFETY"}}),
    ]:
        try:
            providers.parse_response(entry, body)
        except providers.ProviderError as e:
            assert e.category == "output"
        else:
            assert False, body


def test_gemini_refusal_surfaces_block_reason():
    try:
        providers.parse_response("x" and {"provider": "gemini"},
                                 {"promptFeedback": {"blockReason": "SAFETY"}})
    except providers.ProviderError as e:
        assert "SAFETY" in e.message


def test_classify_status_transient_vs_permanent():
    for status in (408, 425, 429, 500, 502, 503, 504):
        assert providers.classify_status(status).category == "transient"
        assert providers.classify_status(status).retry_after is None
    for status in (400, 401, 403, 404):
        assert providers.classify_status(status).category == "permanent"
    assert providers.classify_status(429, "", retry_after=7).retry_after == 7


def test_classify_network():
    assert providers.classify_network(TimeoutError()).category == "transient"
    assert providers.classify_network(ConnectionResetError()).category == "transient"


def test_models_url_and_parse_models():
    assert providers.models_url({"provider": "openai"}) == \
        "https://api.openai.com/v1/models"
    assert providers.models_url({"provider": "ollama"}) == \
        "http://localhost:11434/api/tags"
    assert providers.parse_models(
        {"provider": "openai"}, {"data": [{"id": "b"}, {"id": "a"}]}) == ["a", "b"]
    assert providers.parse_models(
        {"provider": "ollama"}, {"models": [{"name": "llama3"}]}) == ["llama3"]
    # gemini: only chat-capable models, name prefix stripped
    gem = {"models": [
        {"name": "models/gemini-1.5-pro", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/text-embedding", "supportedGenerationMethods": ["embedContent"]},
    ]}
    assert providers.parse_models({"provider": "gemini"}, gem) == ["gemini-1.5-pro"]


def test_specs_declare_no_fabricated_metadata():
    # every cloud provider documents where API keys come from (not subscriptions)
    for pid, spec in providers.PROVIDERS.items():
        if spec.id in ("custom", "ollama"):
            continue  # user-supplied / local endpoint; no place to point at
        assert spec.key_url.startswith("https://"), pid
