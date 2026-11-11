import asyncio
import json

from services.chunking import build_doc_chunks, merge_extraction
from services import ai_assist


def _table(n_rows):
    rows = [{"Name": f"Person {i}", "Email": f"p{i}@example.com", "Phone": f"9000000{i:03d}",
             "_row": i + 2, "_sheet": "Sheet1"}
            for i in range(n_rows)]
    return {"sheet": "Sheet1", "headers": ["Name", "Email", "Phone"], "rows": rows}


def test_chunks_cover_every_row_exactly_once():
    table = _table(120)
    chunks = build_doc_chunks(table, max_chars=2000)
    assert len(chunks) > 1
    seen = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("row "):
                seen.append(int(line.split(":", 1)[0].split()[1]))
    assert sorted(seen) == list(range(2, 122))


def test_chunks_carry_absolute_row_numbers_and_markers():
    table = _table(3)
    chunks = build_doc_chunks(table)
    assert "chunk 1 of 1" in chunks[0]
    assert "row 2:" in chunks[0]
    assert "UNTRUSTED SOURCE CONTENT" in chunks[0]
    assert "_row" not in chunks[0]  # internal provenance keys are not leaked


def test_merge_dedups_by_email_and_records_conflict():
    a = {"contacts": [{"name": "Asha Rao", "email_primary": "a@x.com",
                       "phone_primary": "1111111"}]}
    b = {"contacts": [{"name": "Asha R", "email_primary": "a@x.com",
                       "company_name": "Acme"}]}
    merged = merge_extraction([a, b])
    assert len(merged["contacts"]) == 1
    c = merged["contacts"][0]
    assert c["name"] == "Asha Rao"          # first chunk wins on conflict
    assert c["company_name"] == "Acme"      # gap filled from chunk 2
    assert any("name" in w["message"] for w in merged["warnings"])


def test_merge_keeps_unidentifiable_contacts():
    a = {"contacts": [{"name": None, "phone_primary": None}, {"name": None}]}
    merged = merge_extraction([a])
    assert len(merged["contacts"]) == 2


def test_ai_assist_merges_chunks_and_validates(monkeypatch):
    table = _table(2)
    table["rows"] = [
        {"Name": "Asha Rao", "Email": "asha@example.com", "Phone": "9876543210",
         "_row": 2, "_sheet": "S"},
        {"Name": "Bob Ray", "Email": "bob@example.com", "Phone": "9876543211",
         "_row": 3, "_sheet": "S"},
    ]
    calls = []

    async def fake_extract(chain, prompt, **kwargs):
        calls.append(prompt)
        # One contact per chunk, same payload shape the contract expects.
        row_lines = [l for l in prompt.splitlines() if l.startswith("row ")]
        contacts = []
        for line in row_lines:
            email = line.split("Email=")[-1].split(",")[0].strip()
            name = line.split("Name=")[-1].split(",")[0].strip()
            contacts.append({"name": name, "company_name": None,
                             "email_primary": email, "email_secondary": None,
                             "phone_primary": None, "phone_secondary": None,
                             "phone_country": None, "whatsapp": None,
                             "position": None, "address": None, "city": None,
                             "pincode": None, "website": None,
                             "confidence": "high",
                             "field_evidence": {
                                 "name": {"excerpt": name, "confidence": "high"},
                                 "email_primary": {"excerpt": email, "confidence": "high"}}})
        return {"schema_version": "crm-extraction.v1", "source_type": "spreadsheet",
                "companies": [], "contacts": contacts, "emails": [],
                "call_logs": [], "unmapped_fields": [], "warnings": []}, "fake/model"

    monkeypatch.setattr(ai_assist.llm, "extract", fake_extract)
    cfg = {"reliability": {}}
    out, notes = asyncio.run(ai_assist.assist_document(
        table, name="t.xlsx", chain=[{"provider": "fake"}], cfg=cfg,
        source_type="spreadsheet"))
    assert out
    assert notes == []
    emails = {c["email_primary"] for c in out}
    assert emails == {"asha@example.com", "bob@example.com"}


def test_ai_assist_returns_empty_on_total_failure(monkeypatch):
    async def fake_extract(chain, prompt, **kwargs):
        return None, "all providers failed"

    monkeypatch.setattr(ai_assist.llm, "extract", fake_extract)
    table = _table(1)
    out, notes = asyncio.run(ai_assist.assist_document(
        table, name="t.xlsx", chain=[{"provider": "fake"}], cfg={"reliability": {}},
        source_type="spreadsheet"))
    assert out == []
    assert notes
