"""Regressions for audited settings, import, and contact workflows."""
import asyncio
from contextlib import closing
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import load_workbook

import config
import db
import llm
from app import app
from services import extract, staging


EML = (
    b"From: Alex Example <alex@example.com>\r\n"
    b"To: review@example.com\r\nCc: team@example.com\r\nBcc: archive@example.com\r\n"
    b"Subject: Contact details\r\n\r\nRegards,\r\nAlex Example\r\n"
)


def test_eml_source_fields_survive_approval_and_excel_export(data_dir):
    with TestClient(app) as client:
        uploaded = client.post("/api/intake", files={"files": ("Example.eml", EML)}).json()
        assert uploaded["results"][0]["status"] == "OK"
        assert client.get(f'/api/jobs/{uploaded["job_id"]}').json()["state"] == "done"
        row = client.get("/api/staged-contacts").json()["rows"][0]
        patch = client.patch(f'/api/staged-contacts/{row["id"]}', json={"fields": {
            "phone_primary": "9876543210", "phone_secondary": "9000000001, 9000000002",
            "company": "Example Ltd", "designation": "Engineer", "address": "10 Example Street",
            "city": "Mumbai", "pincode": "400001", "website": "example.com",
        }})
        assert patch.status_code == 200
        assert client.post(f'/api/staged-contacts/{row["id"]}/approve').json()["approved"] == 1
        contact = client.get("/api/contacts").json()["rows"][0]
        details = client.get(f'/api/contacts/{contact["id"]}').json()
        assert details["email_primary"] == "alex@example.com"
        assert details["phone_secondary"] == "9000000001"
        assert [details[key] for key in ("designation", "address", "city", "pincode", "website")] == [
            "Engineer", "10 Example Street", "Mumbai", "400001", "example.com",
        ]
        source = details["email_sources"][0]
        assert source["source_email_id"] and source["pushed_to_crm"] and source["created_at"]
        assert source["source_file"] == "Example.eml"
        assert [source[key] for key in ("to_emails", "cc_emails", "bcc_emails")] == [
            "review@example.com", "team@example.com", "archive@example.com",
        ]
        assert client.get("/api/history").json()["results"][0]["file"] == "Example.eml"
        export = client.get("/api/contacts/export")
        workbook = load_workbook(BytesIO(export.content))
        try:
            assert workbook.sheetnames == ["Contacts", "Email sources"]
            assert list(workbook["Email sources"].values)[1][-4:-1] == (
                "review@example.com", "team@example.com", "archive@example.com",
            )
        finally:
            workbook.close()


def test_local_only_and_smart_import_use_saved_policy(data_dir, monkeypatch):
    async def external_call(*args, **kwargs):
        raise AssertionError("Local-only mode called a provider")

    monkeypatch.setattr(llm, "extract", external_call)
    settings = config.load()
    settings.update(mode="local_only", import_policy="smart_import",
                    chain=[{"provider": "ollama", "model": "unused"}])
    config.save(settings)
    with TestClient(app) as client:
        csv = b"Name,Email\nAlex Example,alex@example.com\n"
        for expected in (1, 0):
            response = client.post("/api/intake", files={"files": ("contacts.csv", csv)}).json()
            assert response["results"][0]["imported"] == expected
        response = client.post("/api/intake", files={"files": ("source.eml", EML)}).json()
        assert response["results"][0]["status"] == "OK"
        assert client.get("/api/contacts").json()["total"] == 1
        assert client.get("/api/staged-contacts/dedup-check", params={"email": "alex@example.com"}).json()["is_duplicate"]


def test_failed_file_rolls_back_email_and_staging(data_dir, tmp_path, monkeypatch):
    path = tmp_path / "source.eml"
    path.write_bytes(EML)
    real_stage = staging.stage_contacts

    def stage_then_fail(*args, **kwargs):
        real_stage(*args, **kwargs)
        raise ValueError("late staging failure")

    monkeypatch.setattr(staging, "stage_contacts", stage_then_fail)
    with closing(db.connect()) as con:
        outcome = asyncio.run(extract.process_source(con, str(path)))
        con.commit()
        assert outcome.status == "ERROR"
        assert con.execute("SELECT COUNT(*) FROM staged_contacts").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM eml_emails").fetchone()[0] == 0
        assert con.execute("SELECT status FROM processed_files").fetchone()[0] == "error"


def test_document_gap_fill_keeps_local_values_and_ai_evidence(data_dir, tmp_path, monkeypatch):
    path = tmp_path / "contacts.csv"
    path.write_text("Name,Email,Notes\nAlex Example,alex@example.com,Mumbai\n", encoding="utf-8")

    async def fake_ai(chain, prompt, *, validate_output, **kwargs):
        payload = {"schema_version": "crm-extraction.v1", "source_type": "csv",
                   "companies": [], "emails": [], "call_logs": [], "unmapped_fields": [], "warnings": [],
                   "contacts": [{"name": "Different Name", "email_primary": "alex@example.com", "city": "Mumbai",
                                 "confidence": "high", "field_evidence": {
                                     "name": {"excerpt": "Alex Example", "confidence": "high"},
                                     "email_primary": {"excerpt": "alex@example.com", "confidence": "high"},
                                     "city": {"excerpt": "Mumbai", "confidence": "high"},
                                 }}]}
        assert validate_output(payload)
        return payload, "fixture"

    monkeypatch.setattr(llm, "extract", fake_ai)
    with closing(db.connect()) as con:
        outcome = asyncio.run(extract.process_source(
            con, str(path), chain=[{"provider": "ollama"}], cfg={"mode": "ai_enrichment"},
        ))
        row = con.execute("SELECT name, city, field_evidence FROM staged_contacts").fetchone()
        assert outcome.staged == 1
        assert row["name"] == "Alex Example" and row["city"] == "Mumbai"
        assert '"excerpt": "Mumbai"' in row["field_evidence"]


def test_provider_type_and_watcher_settings(data_dir):
    with TestClient(app) as client:
        created = client.post("/api/providers", json={"provider": "ollama", "model": "example"}).json()
        assert created[0]["provider"] == "ollama"
        assert client.post("/api/settings", json={"watch_enabled": True}).json()["watch"] is True
        assert client.post("/api/settings", json={"watch": False}).json()["watch"] is False
        company = client.post("/api/companies", json={"name": "Example Ltd"}).json()["company"]
        assert client.get("/api/companies").json()["total"] == 1
        assert client.get(f'/api/companies/{company["id"]}').json()["name"] == "Example Ltd"
        assert client.delete(f'/api/companies/{company["id"]}').status_code == 200
        invalid = client.post("/api/providers", json={"api_key": "temporary-test-key"})
        assert invalid.status_code == 422
        assert "temporary-test-key" not in invalid.text


def test_schema_invalid_provider_response_falls_through(monkeypatch):
    calls = []
    llm.breaker_reset()

    async def fake_attempt(entry, system, prompt, timeout):
        calls.append(entry["provider"])
        return '{"valid": true}' if entry["provider"] == "ollama" else '{"other": true}'

    monkeypatch.setattr(llm, "_one_attempt", fake_attempt)
    try:
        result, _ = asyncio.run(llm.extract(
            [{"provider": "openai", "model": "fixture"}, {"provider": "ollama", "model": "fixture"}],
            "synthetic test input", validate_output=lambda data: data.get("valid") is True,
        ))
        assert result == {"valid": True}
        assert calls == ["openai", "openai", "ollama"]
    finally:
        llm.breaker_reset()


def test_approval_creates_new_contact_when_previous_match_was_deleted(data_dir):
    with TestClient(app) as client:
        ids = []
        for _ in range(2):
            uploaded = client.post("/api/intake", files={"files": ("example.eml", EML)}).json()
            assert uploaded["results"][0]["status"] == "OK"
            row = max(client.get("/api/staged-contacts").json()["rows"], key=lambda row: row["id"])
            assert client.post(f'/api/staged-contacts/{row["id"]}/approve').json()["approved"] == 1
            recent = client.get("/api/contacts").json()["rows"][0]
            ids.append(recent["id"])
            if len(ids) == 1:
                assert client.delete(f'/api/contacts/{recent["id"]}').status_code == 200
        assert ids[0] != ids[1]
