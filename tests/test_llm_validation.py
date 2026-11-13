# tests/test_llm_validation.py — LLM validation tests

from llm import parse_json, _redact

def test_parse_json_valid():
    raw = '{"name": "Test", "email": "test@example.com"}'
    result = parse_json(raw)
    assert result is not None
    assert result["name"] == "Test"
    assert result["email"] == "test@example.com"

def test_parse_json_null_values():
    raw = '{"name": "Test", "email": null, "company": "null"}'
    result = parse_json(raw)
    assert result is not None
    assert result["name"] == "Test"
    assert result["email"] is None
    assert result["company"] is None

def test_parse_json_oversized_field():
    raw = '{"name": "' + 'A' * 200 + '"}'
    result = parse_json(raw)
    assert result is not None
    assert len(result["name"]) <= 100

def test_parse_json_invalid_email():
    raw = '{"name": "Test", "email": "not-an-email"}'
    result = parse_json(raw)
    assert result is not None
    assert result["email"] is None

def test_parse_json_strips_fences():
    raw = '```json\n{"name": "Test"}\n```'
    result = parse_json(raw)
    assert result is not None
    assert result["name"] == "Test"

def test_parse_json_empty():
    assert parse_json("") is None
    assert parse_json(None) is None

def test_parse_json_list():
    raw = '[{"name": "First"}]'
    result = parse_json(raw)
    assert result is not None
    assert result["name"] == "First"

def test_redact():
    msg = "Error with key sk-abc123"
    entry = {"api_key": "sk-abc123"}
    result = _redact(msg, entry)
    assert "sk-abc123" not in result
    assert "***" in result