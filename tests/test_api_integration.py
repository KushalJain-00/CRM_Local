# tests/test_api_integration.py — end-to-end API contract tests on a temporary
# SQLite database (conftest `data_dir`: monkeypatched config.data_dir + db.init(),
# which auto-applies the migration train on non-live files).
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import db
from app import app

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]


def _seed_contact(con, **kw):
    defaults = dict(
        name="Ada Lovelace", email_primary="ada@example.com", email_secondary=None,
        phone_primary="9876543210", phone_secondary=None, company="Analytical Engines",
        designation=None, address=None, city="London", pincode=None, website=None,
        whatsapp=None, position=None, files=None, email_key=None, phone_key=None,
        name_key=None, company_key=None, website_key=None,
        source_file="a.xlsx", source_row=1, extraction_run_id=None, field_origin="xlsx",
        created_at="2026-01-01T00:00:00", updated_at="2026-01-01T00:00:00",
    )
    defaults.update(kw)
    cols = ", ".join(defaults)
    marks = ", ".join(["?"] * len(defaults))
    cur = con.execute(f"INSERT INTO contacts ({cols}) VALUES ({marks})", list(defaults.values()))
    con.commit()
    return cur.lastrowid


def _seed_staged(con, **kw):
    defaults = dict(
        source_type="xlsx", source_file="leads.xlsx", source_row=1,
        name="Grace Hopper", email="grace@example.com", phone_primary="9812345678",
        company="Compiler Corp", confidence=0.9,
        review_status="NEW", dedup_status="NOT_CHECKED", import_status="NOT_IMPORTED",
        created_at="2026-02-01T00:00:00", updated_at="2026-02-01T00:00:00",
    )
    defaults.update(kw)
    cols = ", ".join(defaults)
    marks = ", ".join(["?"] * len(defaults))
    cur = con.execute(f"INSERT INTO staged_contacts ({cols}) VALUES ({marks})", list(defaults.values()))
    con.commit()
    return cur.lastrowid


def _seed_email(con, **kw):
    defaults = dict(
        file_name="a.eml", file_path="/tmp/a.eml", subject="Hello", date="2026-03-01T10:00:00",
        sender_name="Sender One", sender_email="sender@example.com",
        to_emails="", cc_emails="", bcc_emails="", body_text="body",
        has_signature=0, signature_block=None, processed_at="2026-03-01T10:00:05",
        created_at="2026-03-01T10:00:05",
    )
    defaults.update(kw)
    cols = ", ".join(defaults)
    marks = ", ".join(["?"] * len(defaults))
    cur = con.execute(f"INSERT INTO eml_emails ({cols}) VALUES ({marks})", list(defaults.values()))
    con.commit()
    return cur.lastrowid


def _seed_processed(con, **kw):
    defaults = dict(path="/tmp/f1.xlsx", size=100, mtime=1000.0, status="ok",
                    detail=None, contacts_found=4, processed_at="2026-04-01T00:00:00")
    defaults.update(kw)
    cols = ", ".join(defaults)
    marks = ", ".join(["?"] * len(defaults))
    con.execute(f"INSERT INTO processed_files ({cols}) VALUES ({marks})", list(defaults.values()))
    con.commit()


# ── contacts ─────────────────────────────────────────────────────────────────

def test_contacts_empty_db(data_dir):
    r = client.get("/api/contacts")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == [] and body["total"] == 0
    assert body["page"] == 1 and body["pageSize"] == 25 and body["totalPages"] == 0


def test_contacts_pagination_search_sort(data_dir):
    con = db.connect("crm")
    for i in range(5):
        _seed_contact(con, name=f"Person {i}", email_primary=f"p{i}@example.com",
                      company="Acme" if i % 2 else "Beta",
                      created_at=f"2026-01-0{i + 1}T00:00:00")
    con.close()

    r = client.get("/api/contacts?page=2&size=2&sort=id&dir=asc")
    body = r.json()
    assert r.status_code == 200 and body["total"] == 5
    assert body["pageSize"] == 2 and body["totalPages"] == 3 and len(body["rows"]) == 2

    r = client.get("/api/contacts?q=person%201&sort=id&dir=asc")
    assert [row["name"] for row in r.json()["rows"]] == ["Person 1"]

    r = client.get("/api/contacts?q=beta&sort=company&dir=asc")
    assert all(row["company"] == "Beta" for row in r.json()["rows"])

    assert client.get("/api/contacts?sort=;DROP%20TABLE%20contacts").status_code == 422
    assert client.get("/api/contacts?sort=bogus").status_code == 422
    assert client.get("/api/contacts?dir=sideways").status_code == 422
    assert client.get("/api/contacts?page=0").status_code == 422
    assert client.get("/api/contacts?size=10000").status_code == 422


def test_contacts_soft_delete_and_patch(data_dir):
    con = db.connect("crm")
    cid = _seed_contact(con, name="Delete Me", email_primary="gone@example.com")
    con.close()

    r = client.patch(f"/api/contacts/{cid}", json={"fields": {"name": "Renamed", "email_primary": "new@example.com"}})
    assert r.status_code == 200
    assert r.json()["contact"]["name"] == "Renamed"

    con = db.connect("crm")
    row = con.execute("SELECT email_key FROM contacts WHERE id = ?", (cid,)).fetchone()
    con.close()
    assert row["email_key"] == "new@example.com"

    r = client.patch(f"/api/contacts/{cid}", json={"fields": {"not_a_column": "x"}})
    assert r.status_code == 422
    assert client.patch("/api/contacts/999999", json={"fields": {"name": "x"}}).status_code == 404

    assert client.delete(f"/api/contacts/{cid}").json()["ok"] is True
    assert client.get("/api/contacts").json()["total"] == 0   # soft-deleted rows hidden
    assert client.get(f"/api/contacts/{cid}").status_code == 404
    assert client.delete(f"/api/contacts/{cid}").status_code == 404


# ── emails ───────────────────────────────────────────────────────────────────

def test_emails_empty_db(data_dir):
    r = client.get("/api/emails")
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == [] and body["total"] == 0


def test_emails_populated_with_contact_counts(data_dir):
    con = db.connect("crm")
    e1 = _seed_email(con, subject="Quarterly plan", sender_name="Priya")
    e2 = _seed_email(con, subject="Lunch?", sender_name="Rahul", date="2026-03-05T10:00:00")
    sid = _seed_staged(con, email="friend@example.com", created_at="2026-03-01T00:00:00")
    con.execute(
        "INSERT INTO email_staged_links (email_id, staged_contact_id, created_at)"
        " VALUES (?, ?, datetime('now'))", (e1, sid))
    con.commit()
    con.close()

    body = client.get("/api/emails").json()
    assert body["total"] == 2
    by_subject = {row["subject"]: row for row in body["rows"]}
    assert by_subject["Quarterly plan"]["contact_count"] == 1
    assert by_subject["Lunch?"]["contact_count"] == 0

    assert client.get("/api/emails?q=priya").json()["total"] == 1
    assert client.get("/api/emails?page=0").status_code == 422
    assert client.get("/api/emails?size=501").status_code == 422


# ── history ─────────────────────────────────────────────────────────────────

def test_history_empty_db(data_dir):
    r = client.get("/api/history")
    assert r.status_code == 200
    assert r.json() == {"results": [], "total": 0}


def test_history_lists_processed_files(data_dir):
    con = db.connect("crm")
    _seed_processed(con, path="/data/inbox/older.xlsx", processed_at="2026-04-01T00:00:00",
                    contacts_found=7, status="ok")
    _seed_processed(con, path="/data/inbox/newer.eml", processed_at="2026-04-02T00:00:00",
                    contacts_found=2, status="error", detail="parse failed")
    con.close()

    body = client.get("/api/history").json()
    assert body["total"] == 2
    assert body["results"][0]["file"] == "newer.eml"      # newest first
    assert body["results"][0]["status"] == "error"
    assert body["results"][0]["contacts_found"] == 2
    assert body["results"][1]["file"] == "older.xlsx"
    assert body["results"][1]["contacts_found"] == 7


# ── dedup rules + status ────────────────────────────────────────────────────

def test_dedup_rules_shape(data_dir):
    r = client.get("/api/dedup-rules")
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert rows and all({"field", "severity", "status"} <= set(row) for row in rows)


def test_status_extended_counts(data_dir):
    con = db.connect("crm")
    _seed_contact(con, name="New Person", email_primary="new@example.com",
                  created_at="2099-01-01T00:00:00")  # inside 30-day window? no — future date counts as >= cutoff
    _seed_email(con, subject="s")
    _seed_processed(con)
    _seed_staged(con, email="staged@example.com", review_status="READY")
    con.close()

    body = client.get("/api/status").json()
    counts = body["counts"]
    for key in ("crm", "emails", "processed_files", "new", "staged",
                "invalid_emails", "invalid_phones", "incomplete_records", "duplicates"):
        assert key in counts, f"missing counts key {key}"
    assert counts["crm"] == 1 and counts["processed_files"] == 1 and counts["staged"] == 1


# ── staged contacts: list / patch / approve / reject / dismiss ──────────────

def test_staged_list_pagination(data_dir):
    con = db.connect("crm")
    for i in range(3):
        _seed_staged(con, email=f"s{i}@example.com", name=f"Staged {i}")
    con.close()

    body = client.get("/api/staged-contacts?page=1&size=2").json()
    assert body["total"] == 3 and len(body["rows"]) == 2 and body["totalPages"] == 2
    assert client.get("/api/staged-contacts?page=0").status_code == 422
    assert client.get("/api/staged-contacts?size=101").status_code == 422


def test_staged_approve_creates_canonical_contact(data_dir):
    con = db.connect("crm")
    sid = _seed_staged(con, email="approve@example.com", name="Future Contact")
    con.close()

    r = client.post(f"/api/staged-contacts/{sid}/approve")
    assert r.status_code == 200 and r.json()["approved"] == 1

    con = db.connect("crm")
    row = con.execute(
        "SELECT * FROM contacts WHERE lower(email_primary) = 'approve@example.com'").fetchone()
    staged = con.execute("SELECT * FROM staged_contacts WHERE id = ?", (sid,)).fetchone()
    con.close()
    assert row is not None and row["name"] == "Future Contact"
    assert staged["review_status"] == "APPROVED"
    assert staged["import_status"] == "NEW_CONTACT_CREATED"
    assert staged["crm_contact_id"] == row["id"]          # provenance preserved

    # replay is a no-op: no duplicate canonical contact, no double count
    r = client.post(f"/api/staged-contacts/{sid}/approve")
    assert r.status_code == 200 and r.json()["already_approved"] == 1
    con = db.connect("crm")
    assert con.execute(
        "SELECT count(*) FROM contacts WHERE lower(email_primary) = 'approve@example.com'").fetchone()[0] == 1
    con.close()


def test_staged_approve_enriches_existing_local_wins(data_dir):
    con = db.connect("crm")
    cid = _seed_contact(con, name="Existing Person", email_primary="keep@example.com",
                        phone_primary=None, company="KeepCo")
    sid = _seed_staged(con, email="keep@example.com", name="Existing Person",
                       phone_primary="9000000001", company="NewCo")
    con.close()

    r = client.post(f"/api/staged-contacts/{sid}/approve")
    assert r.status_code == 200

    con = db.connect("crm")
    row = con.execute("SELECT * FROM contacts WHERE id = ?", (cid,)).fetchone()
    staged = con.execute("SELECT * FROM staged_contacts WHERE id = ?", (sid,)).fetchone()
    con.close()
    assert row["phone_primary"] == "9000000001"    # empty field filled
    assert row["company"] == "KeepCo"              # local wins — existing not overwritten
    assert row["name"] == "Existing Person"
    assert staged["import_status"] == "EXISTING_CONTACT_ENRICHED"


def test_staged_reject_and_dismiss_block_approval(data_dir):
    con = db.connect("crm")
    sid_r = _seed_staged(con, email="rej@example.com")
    sid_d = _seed_staged(con, email="dis@example.com")
    sid_a = _seed_staged(con, email="appr@example.com")
    con.close()

    assert client.post(f"/api/staged-contacts/{sid_r}/reject").status_code == 200
    assert client.post(f"/api/staged-contacts/{sid_d}/dismiss").status_code == 200
    assert client.post(f"/api/staged-contacts/{sid_r}/reject").status_code in (200, 409)
    assert client.post("/api/staged-contacts/999999/reject").status_code == 404
    assert client.post("/api/staged-contacts/999999/dismiss").status_code == 404

    client.post(f"/api/staged-contacts/{sid_a}/approve")
    assert client.post(f"/api/staged-contacts/{sid_a}/reject").status_code == 409
    assert client.post(f"/api/staged-contacts/{sid_a}/dismiss").status_code == 409


def test_staged_patch_fields(data_dir):
    con = db.connect("crm")
    sid = _seed_staged(con, email="patch@example.com", name="Old Name")
    con.close()

    r = client.patch(f"/api/staged-contacts/{sid}",
                     json={"fields": {"name": "New Name", "company": "NewCo"}})
    assert r.status_code == 200
    con = db.connect("crm")
    row = con.execute("SELECT name, company FROM staged_contacts WHERE id = ?", (sid,)).fetchone()
    con.close()
    assert row["name"] == "New Name" and row["company"] == "NewCo"

    assert client.patch(f"/api/staged-contacts/{sid}",
                        json={"fields": {"bogus_col": "x"}}).status_code == 422
    assert client.patch("/api/staged-contacts/999999",
                        json={"fields": {"name": "x"}}).status_code == 404


def test_staged_bulk_action_dispatch(data_dir):
    """Regression: bulk-action used to ignore `action` and always approve."""
    con = db.connect("crm")
    sid = _seed_staged(con, email="bulk@example.com")
    con.close()

    r = client.post("/api/staged-contacts/bulk-action",
                    json={"staged_ids": [sid], "action": "reject"})
    assert r.status_code == 200
    con = db.connect("crm")
    status = con.execute("SELECT review_status FROM staged_contacts WHERE id = ?",
                         (sid,)).fetchone()[0]
    approved = con.execute(
        "SELECT count(*) FROM contacts WHERE lower(email_primary) = 'bulk@example.com'").fetchone()[0]
    con.close()
    assert status == "REJECTED" and approved == 0

    assert client.post("/api/staged-contacts/bulk-action",
                       json={"staged_ids": [sid], "action": "explode"}).status_code == 422


def test_staged_missing_table_degrades_to_503(data_dir, monkeypatch):
    """If the staging schema is absent (live DB pending the gated migration),
    routes answer 503 with an actionable message — never a bare 500."""
    import sqlite3
    from api import staged as staged_api
    from fastapi import HTTPException

    con = sqlite3.connect(":memory:")
    with pytest.raises(HTTPException) as exc:
        staged_api._require_staged_table(con)
    assert exc.value.status_code == 503


# ── frontend ↔ backend contract ─────────────────────────────────────────────

def _frontend_api_paths():
    js = (ROOT / "static" / "app.js").read_text("utf-8")
    paths = set()
    for m in re.finditer(r"""api(?:FormData)?\(\s*['"`](/api/[^'"`]*)['"`]""", js):
        p = m.group(1)
        p = re.sub(r"\$\{[^}]*\}", "{}", p)          # template interpolation → {}
        p = re.sub(r"[?&].*$", "", p)                # strip query string
        if p.endswith("/"):                          # '/api/x/' + id  →  '/api/x/<id>'
            p = p[:-1] + "/{}"
        paths.add(p)
    return paths


def test_every_frontend_api_call_maps_to_a_route():
    routes = {}
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if path and methods and path.startswith("/api"):
            routes[path] = methods

    def _matches(path: str) -> bool:
        pattern = "^" + re.escape(path)
        pattern = pattern.replace(r"\{\}", r"[^/]+")       # {} placeholders match one segment
        return any(re.fullmatch(pattern, route_path) for route_path in routes)

    missing = sorted(p for p in _frontend_api_paths() if not _matches(p))
    assert missing == [], f"frontend calls without a backend route: {missing}"
