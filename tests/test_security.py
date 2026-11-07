# tests/test_security.py — Round 4 security fixes (SEC-01/02/03/07/09/10)
import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import db
import pipeline
from app import MASKED_KEY, app
from services.eml_processor import ParsedEml, build_llm_prompt

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]
SECRET = "sk-live-SECRETVALUE123"


def _seed() -> None:
    cfg = config.load()
    cfg["chain"] = [
        {"provider": "openrouter", "model": "m", "api_key": SECRET, "base_url": "", "enabled": True}
    ]
    config.save(cfg)


def _chain() -> list:
    return config.load().get("chain") or []


# ── SEC-01: no raw key material on /api/settings response ────────────────
# /api/config is retired (D-011 → 410); key masking lives on /api/settings
@pytest.mark.parametrize("path", ["/api/settings"])
def test_get_never_returns_raw_key(data_dir, path):
    _seed()
    r = client.get(path)
    assert r.status_code == 200
    assert SECRET not in r.text
    entry = r.json()["chain"][0]
    assert entry["api_key"] == MASKED_KEY
    assert entry["api_key_set"] is True
    assert entry["id"] == "0"


def test_post_response_is_masked(data_dir):
    _seed()
    r = client.post("/api/settings", json={
        "chain": [{"id": "0", "provider": "openrouter", "model": "m", "api_key": "brand-new-key", "enabled": True}]
    })
    assert r.status_code == 200
    assert "brand-new-key" not in r.text
    assert r.json()["chain"][0]["api_key"] == MASKED_KEY
    assert _chain()[0]["api_key"] == "brand-new-key"  # write still lands


def test_masked_roundtrip_keeps_stored_key(data_dir):
    _seed()
    masked = client.get("/api/settings").json()["chain"]
    r = client.post("/api/settings", json={"chain": masked})
    assert r.status_code == 200
    assert _chain()[0]["api_key"] == SECRET  # MASKED_KEY keeps, not clobbers


def test_empty_or_absent_key_keeps_stored(data_dir):
    _seed()
    base = {"id": "0", "provider": "openrouter", "model": "m", "enabled": True}
    client.post("/api/settings", json={"chain": [dict(base, api_key="") ]})
    assert _chain()[0]["api_key"] == SECRET
    client.post("/api/settings", json={"chain": [base]})  # api_key omitted entirely
    assert _chain()[0]["api_key"] == SECRET


def test_omitted_entry_deletes_credential(data_dir):
    _seed()
    r = client.post("/api/settings", json={"chain": []})
    assert r.status_code == 200
    assert _chain() == []


def test_non_string_key_rejected(data_dir):
    _seed()
    r = client.post("/api/settings", json={"chain": [{"provider": "x", "api_key": 123}]})
    assert r.status_code == 422
    assert _chain()[0]["api_key"] == SECRET  # stored key untouched


# ── SEC-03: Origin / Host first-invalid rejection ────────────────────────────
def test_evil_origin_rejected_before_write(data_dir):
    _seed()
    r = client.post("/api/settings", json={"theme": "dark"},
                    headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert config.load()["theme"] != "dark"  # nothing was written


def test_valid_loopback_origin_allowed(data_dir):
    c = TestClient(app, base_url="http://127.0.0.1:8000")
    r = c.get("/api/settings", headers={"Origin": "http://127.0.0.1:8000"})
    assert r.status_code == 200
    r = c.post("/api/settings", json={"theme": "dark"},
               headers={"Origin": "http://localhost:8000"})
    assert r.status_code == 200
    assert config.load()["theme"] == "dark"


def test_external_host_rejected(data_dir):
    c = TestClient(app, base_url="http://evil.example:8000")
    r = c.get("/api/settings")
    assert r.status_code == 403


def test_absent_origin_and_loopback_host_pass(data_dir):
    r = client.get("/api/settings")  # TestClient: no Origin, Host=testserver
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"


# ── SEC-09: config.json owner-only permissions ──────────────────────────────
@pytest.mark.skipif(os.name == "nt", reason="POSIX modes only")
def test_lock_down_restores_0600(data_dir):
    config.save({"chain": []})
    os.chmod(config.config_path(), 0o644)
    config.lock_down()
    mode = stat.S_IMODE(config.config_path().stat().st_mode)
    assert mode == 0o600, oct(mode)


# ── SEC-07: scan caps ───────────────────────────────────────────────────────
def test_size_cap_marks_error_and_excludes(data_dir, tmp_path):
    eml_dir = tmp_path / "eml"
    eml_dir.mkdir()
    big = eml_dir / "big.eml"
    big.write_bytes(b"x" * (11 * 1024 * 1024))  # > MAX_SCAN_SIZE (10MB)
    (eml_dir / "ok.eml").write_text("Subject: hi\n\nbody\n", "utf-8")

    pending = pipeline._pending(str(eml_dir), "eml", pipeline.EML_EXTS)
    assert pending == [str(eml_dir / "ok.eml")]

    con = db.connect("eml")
    try:
        row = con.execute("SELECT status, detail FROM processed_files WHERE path=?",
                          (str(big),)).fetchone()
    finally:
        con.close()
    assert row is not None and row[0] == "error"
    assert "cap" in (row[1] or "")


def test_depth_cap_prunes_deep_trees(data_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "MAX_SCAN_DEPTH", 1)
    base = tmp_path / "eml"
    (base / "sub" / "deep").mkdir(parents=True)
    (base / "top.eml").write_text("a", "utf-8")
    (base / "sub" / "mid.eml").write_text("b", "utf-8")
    (base / "sub" / "deep" / "far.eml").write_text("c", "utf-8")
    found = pipeline._files(str(base), pipeline.EML_EXTS)
    names = {Path(p).name for p in found}
    assert names == {"top.eml", "mid.eml"}


def test_file_count_cap(data_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "MAX_SCAN_FILES", 2)
    base = tmp_path / "eml"
    base.mkdir()
    for i in range(4):
        (base / f"f{i}.eml").write_text("a", "utf-8")
    assert len(pipeline._files(str(base), pipeline.EML_EXTS)) == 2


# ── SEC-10: prompt header caps (mirrored to CRM_Developer) ──────────────────
def test_prompt_headers_capped():
    p = build_llm_prompt(ParsedEml(
        subject="S" * 50_000,
        sender_name="N" * 5_000,
        sender_email="e@" + "x" * 500 + ".com",
        date="D" * 500,
    ))
    subject_line = next(l for l in p.splitlines() if l.startswith("Subject: "))
    from_line = next(l for l in p.splitlines() if l.startswith("From: "))
    date_line = next(l for l in p.splitlines() if l.startswith("Date: "))
    assert len(subject_line) - len("Subject: ") <= 200
    assert len(from_line) - len("From: ") <= 100 + 3 + 254 + 2  # name < email >
    assert len(date_line) - len("Date: ") <= 64
    assert len(p) < 10_000  # body_text empty; header bloat cannot dominate


# ── SEC-02: static ratchet — app.js data sinks escaped ───────────────────────
# (Covered by test_ratchet.py::test_app_js_data_sinks_escaped; this space kept
#  for parity with the original test module structure.)
def test_app_js_data_sinks_escaped_placeholder():
    """Placeholder — full check covered by test_ratchet.py."""
    pass
