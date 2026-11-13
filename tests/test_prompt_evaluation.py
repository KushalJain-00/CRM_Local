# tests/test_prompt_evaluation.py — deterministic Layer-1 evaluation of the
# two master prompts' pipeline on a synthetic, PII-free corpus.
# AI-path semantics are exercised through a mocked provider chain (no
# network); provider quality itself is NOT measured here (see
# docs/PROVIDER_VALIDATION.md).
import asyncio
import json
from pathlib import Path

import pytest

from services.adapters import get_adapter

CORPUS = Path(__file__).parent / "evaluation"
TRUTH = json.loads((CORPUS / "ground_truth.json").read_text())
FILES = CORPUS / "files"


def _digits(s: str) -> str:
    import re
    return re.sub(r"\D", "", s or "")


@pytest.mark.parametrize("file_name", sorted(TRUTH["documents"]))
def test_document_extraction_expectations(file_name):
    spec = TRUTH["documents"][file_name]
    adapter = get_adapter(str(FILES / file_name))
    result = asyncio.run(adapter.extract(str(FILES / file_name)))
    found = result.contacts

    expected = spec.get("expected", [])
    assert len(found) >= len(expected), (
        f"{file_name}: expected at least {len(expected)} contacts, "
        f"got {len(found)}: {[vars(c) for c in found]}")

    for exp in expected:
        match = None
        for got in found:
            if exp.get("email_primary") and got.email_primary == exp["email_primary"]:
                match = got
                break
            if exp.get("name") and got.name and got.name.strip().lower() == exp["name"].strip().lower():
                match = got
                break
        assert match is not None, f"{file_name}: no match for {exp}"
        for key, val in exp.items():
            got_val = getattr(match, key, None)
            if key == "phone_primary":
                assert got_val and _digits(got_val) == _digits(val)
            elif val is None:
                assert got_val is None or str(got_val).strip() == ""
            else:
                assert str(got_val).strip().lower() == str(val).strip().lower()

    for null_field in spec.get("expected_null", []):
        for got in found:
            assert getattr(got, null_field, None) is None, f"{file_name}: {null_field} should be null"

    excluded = " ".join(str(getattr(c, f, "")) for c in found for f in
                        ("name", "email_primary", "company", "designation"))
    for token in spec.get("excluded", []):
        assert token.lower() not in excluded.lower(), (
            f"{file_name}: excluded token {token!r} appeared in extraction")


@pytest.mark.parametrize("file_name", sorted(TRUTH["eml"]))
def test_eml_extraction_expectations(file_name):
    spec = TRUTH["eml"][file_name]
    adapter = get_adapter(str(FILES / file_name))
    result = asyncio.run(adapter.extract(str(FILES / file_name)))
    found = result.contacts

    if spec.get("expected_count") == 1:
        assert len(found) == 1, f"{file_name}: expected exactly 1 contact, got {len(found)}"

    for exp in spec["expected"]:
        match = None
        for got in found:
            ok = True
            if exp.get("email_primary"):
                ok = (got.email_primary or "").lower() == exp["email_primary"].lower()
            elif exp.get("name"):
                ok = (got.name or "").strip().lower() == exp["name"].strip().lower()
            if ok:
                match = got
                break
        assert match is not None, f"{file_name}: no match for {exp}"
        for key, val in exp.items():
            if key in ("email_primary", "name"):
                continue
            got_val = getattr(match, key, None)
            if key == "phone_primary":
                assert got_val and _digits(got_val) == _digits(val)
            else:
                assert str(got_val).strip().lower() == str(val).strip().lower()

    for null_field in spec.get("expected_null", []):
        for got in found:
            assert getattr(got, null_field, None) is None, f"{file_name}: {null_field} should be null"

    excluded = " ".join(str(getattr(c, f, "")) for c in found for f in
                        ("name", "email_primary", "company", "designation"))
    for token in spec.get("excluded", []):
        assert token.lower() not in excluded.lower(), (
            f"{file_name}: excluded token {token!r} appeared in extraction")


def test_injection_cell_never_produces_phantom_contacts():
    """The malicious Notes cell must not create extra contacts or emails."""
    result = asyncio.run(get_adapter(str(FILES / "injection.csv")).extract(str(FILES / "injection.csv")))
    assert len(result.contacts) == 1
    got = result.contacts[0]
    assert got.email_primary == "real@kexample.com"
    assert got.name == "Real Person"


def test_injection_attempt_via_ai_path_is_rejected(monkeypatch):
    """A provider that answers the injection with contract-invalid JSON
    contributes ZERO contacts; Layer-1 still stands."""
    import services.ai_assist as ai_assist

    async def poisoned_extract(chain, prompt, **kwargs):
        return ('{"not": "a valid crm-extraction.v1 payload", '
                '"contacts": 999, "schema_version": "wrong"}'), "fake/model"

    monkeypatch.setattr(ai_assist.llm, "extract", poisoned_extract)
    import parse
    table = parse.read_table(str(FILES / "injection.csv"))
    out, notes = asyncio.run(ai_assist.assist_document(
        table, name="injection.csv", chain=[{"provider": "fake"}],
        cfg={"reliability": {}}, source_type="spreadsheet"))
    assert out == []
    assert notes  # explains the failure honestly


def test_ai_injection_payload_ignored_but_valid_gap_filled(monkeypatch):
    """A well-formed provider payload fills the gap; a poisoned one must not
    clobber Layer-1 contacts."""
    import services.ai_assist as ai_assist

    payload = {
        "schema_version": "crm-extraction.v1", "source_type": "spreadsheet",
        "companies": [], "call_logs": [], "unmapped_fields": [], "warnings": [],
        "emails": [],
        "contacts": [
            {"name": "Real Person", "company_name": None,
             "email_primary": "real@kexample.com", "email_secondary": None,
             "phone_primary": None, "phone_secondary": None, "phone_country": None,
             "whatsapp": None, "position": None, "address": None, "city": None,
             "pincode": None, "website": None, "confidence": "high",
             "field_evidence": {
                 "name": {"excerpt": "Real Person", "confidence": "high"},
                 "email_primary": {"excerpt": "real@kexample.com", "confidence": "high"}}},
        ],
    }

    async def fill_extract(chain, prompt, **kwargs):
        return payload, "fake/model"

    monkeypatch.setattr(ai_assist.llm, "extract", fill_extract)
    import parse
    table = parse.read_table(str(FILES / "injection.csv"))
    out, notes = asyncio.run(ai_assist.assist_document(
        table, name="injection.csv", chain=[{"provider": "fake"}],
        cfg={"reliability": {}}, source_type="spreadsheet"))
    assert out and out[0]["email_primary"] == "real@kexample.com"


def test_prompt_assembly_guards_both_masters():
    """Both assembled prompts carry the untrusted markers and the anti-injection
    hierarchy; neither leaks instructions from the source as authority."""
    from services.prompts.store import text as prompt_text
    from services.prompts.contact_extraction import MASTER_SYSTEM_PROMPT
    from services.eml_processor import build_llm_prompt, ParsedEml

    eml_system = prompt_text("eml")
    doc_system = prompt_text("contact")

    for label, p in (("eml", eml_system), ("contact", doc_system)):
        low = p.lower()
        assert "instruction" in low, label  # anti-instruction section present
        assert "untrusted" in low, label
        assert "system prompt" in low, label  # anti-exfiltration instruction present

    p = build_llm_prompt(ParsedEml(
        file_name="x.eml", subject="S", date="D",
        sender_name="A B", sender_email="a@b.com",
        receiver_name="C", receiver_email="c@d.com",
        to_emails="c@d.com", cc_emails=None, bcc_emails=None,
        body_text="hello", has_signature=True, signature_block="A B\na@b.com",
    ))
    assert "BEGIN UNTRUSTED EMAIL CONTENT" in p
    assert "END UNTRUSTED EMAIL CONTENT" in p
