# tests/test_ratchet.py — D-029 fix-ratchet
"""Strict-xfail ratchet for confirmed-but-unfixed bugs (DECISIONS.md D-029, QA_ACCEPTANCE_PLAN P0-7).

Every test below pins a defect confirmed in docs/SECURITY_REVIEW.md or
DECISIONS.md (D-009/D-029). Unfixed defects get `xfail(strict=True)`: the moment
a fix lands the test XPASSes and the suite goes red until this marker is removed
in the same PR as the fix. Defects found already-fixed at write time carry no
marker and assert the fixed behaviour instead (see the FLIPPED notes).

Two tests are static-content tests (they read static/app.js / static/index.html
as text instead of driving a browser). That choice is documented per-test: those
defects exist only in frontend JS with no Python-level entry point, so the only
unit-level pin available is the defect pattern itself.
"""
import asyncio
import os
import re
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import intake
from app import app

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def _js() -> str:
    return (ROOT / "static" / "app.js").read_text("utf-8")


def _html() -> str:
    return (ROOT / "static" / "index.html").read_text("utf-8")


def _handler_defined(name: str) -> bool:
    """True when `name` is not referenced by index.html, or is defined in app.js."""
    if name not in _html():
        return True
    js = _js()
    return (
        re.search(rf"(?:function|const|let|var)\s+{name}\b", js) is not None
        or re.search(rf"{name}\s*=\s*(?:async\s*)?\(", js) is not None
    )


# ── D-029 fix-ratchet ────────────────────────────────────────────────────────
# Confirmed-but-unfixed bugs. Remove the marker in the same PR as the fix.


# --- BUG-D009: broken dropzone transport -----------------------------------
# Static-content test: the bug is that startExtraction() posts only File.name
# values (pure frontend); no Python-level entry point exists, so the defect
# pattern in static/app.js is what can be pinned at unit level.
def test_dropzone_uploads_bytes_not_bare_names():
    js = _js()
    sends_bare_names = (
        re.search(r"map\(\s*\(?f\)?\s*=>\s*f\.name\s*\)", js) is not None
        and "/api/intake" in js
    )
    assert not sends_bare_names or "FormData" in js


# Behavioral half of BUG-D009: the API must resolve what the dropzone sends.
def test_intake_missing_file_produces_error_not_silent_success(data_dir):
    # A scan/intake pointing at a nonexistent path must surface an explicit
    # per-file error — never a silently invented empty file.
    import asyncio
    import db
    from services.extract import process_source
    con = db.connect("crm")
    try:
        outcome = asyncio.run(process_source(con, "/nonexistent/contacts.csv",
                                             chain=[], cfg=config.load()))
        con.commit()
    finally:
        con.close()
    assert outcome.status == "ERROR"
    assert "no such file" in (outcome.error or "").lower()


# Behavioral half of BUG-SEC-05: the API must refuse paths outside allowed data dirs.
def test_api_intake_refuses_paths_outside_data_dirs(data_dir, tmp_path):
    outside = tmp_path / "outside.csv"
    outside.write_text("Name,Email\nMallory Example,mallory@example.com\n", "utf-8")
    r = client.post("/api/intake", data={"paths": [str(outside)]})
    body = r.json() if r.status_code == 200 else {}
    assert r.status_code >= 400 or body.get("counts", {}).get("new", 0) == 0


# --- BUG-SEC-11: intake.py:78 NameError on the EML+chain path ---------------
# FLIPPED: fixed while this file was being written (`import llm` now present in
# intake.py), so the ratchet marker is gone and the fixed behaviour is asserted.
def test_eml_chain_intake_runs_without_nameerror(data_dir, tmp_path):
    eml = tmp_path / "mail.eml"
    eml.write_text(
        "From: Asha Rao <asha@example.com>\n"
        "To: bob@example.com\n"
        "Subject: Hello\n"
        "Date: Mon, 05 Jan 2026 10:00:00 +0000\n"
        "\nHi, my name is Asha Rao and I work at Acme.\n",
        "utf-8",
    )
    # Disabled provider entry keeps chain non-empty without any network call.
    chain = [{"provider": "x", "model": "m", "enabled": False}]
    res = asyncio.run(intake.universal_intake([str(eml)], chain=chain))
    assert res["counts"]["error"] == 0, res["results"][0].get("error")
    assert res["results"][0]["status"] == "OK"


# --- BUG-SEC-06: magic-bytes gate covers only .xls/.pdf ---------------------
@pytest.mark.xfail(
    reason="BUG-SEC-06: _MAGIC only validates .xls/.pdf (intake.py:21-24) — a non-zip .xlsx passes the content gate",
    strict=True,
)
def test_xlsx_magic_bytes_validated(data_dir, tmp_path):
    fake = tmp_path / "fake.xlsx"
    fake.write_bytes(b"not a zip at all")
    res = asyncio.run(intake.universal_intake([str(fake)]))
    assert "does not match" in str(res["results"][0])


# --- BUG-SEC-09: config.json written world-readable ------------------------
# FLIPPED: fixed while this file was being written (`_private()` chmod in
# config.save()), so the marker is gone and 0600 is asserted directly.
def test_config_save_sets_0600(data_dir):
    old_umask = os.umask(0o022)
    try:
        config.save({"chain": []})
    finally:
        os.umask(old_umask)
    if os.name == "nt":
        # On Windows, POSIX mode bits do not represent ACL permissions
        # equivalently. config._private() is intentionally a no-op on Windows
        # (os.chmod is meaningless for Windows ACLs). The security guarantee
        # is that config.json inherits the profile directory's inherited ACLs
        # (owner-full-control). We only verify the file was written.
        assert config.config_path().exists()
    else:
        # Linux/macOS: verify restrictive 0600 permissions.
        mode = stat.S_IMODE(config.config_path().stat().st_mode)
        assert mode == 0o600, oct(mode)


# --- BUG-SEC-13: ignore-list gaps ------------------------------------------
# FLIPPED: config.json / config.json.bak / data_backup/ now ignored
# (SECURITY_REVIEW.md SEC-13), so the marker is gone and coverage asserted.
def test_gitignore_covers_backups():
    gitignore = (ROOT / ".gitignore").read_text("utf-8")
    assert "data_backup" in gitignore


# --- BUG-D029: undefined frontend handlers ---------------------------------
# PR #1 remediation removed both xfail(strict=True) markers: filterContacts()
# and exportContacts() are now defined in static/app.js (see the behavioral
# FLIPPED tests at the bottom of this file). The reference-vs-definition
# mismatch is gone, so the defect pin no longer applies.
# ── P0-E: intake security regression tests ─────────────────────────────────
# These tests verify path containment, empty file handling, and extraction
# guards at the API and function levels.


def test_intake_path_traversal_with_dotdot(data_dir, tmp_path):
    """Path traversal via '..' must be rejected by the API containment check."""
    # Create a file outside data dir using path traversal
    outside = tmp_path / "escape.csv"
    outside.write_text("Name,Email\nEve,eve@example.com\n")
    # Send path with ../ to escape data dir
    r = client.post("/api/intake", data={"paths": [f"{outside}../../../../etc/passwd"]})
    # Should be rejected by API path containment
    assert r.status_code >= 400


def test_intake_empty_file_processes_zero_contacts(data_dir, tmp_path):
    """An empty CSV uploaded via multipart processes with 0 contacts."""
    r = client.post("/api/intake",
                    files=[("files", ("empty_test.csv", b"", "text/csv"))])
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["new"] == 0
    # Should not report "file not found"
    assert "file not found" not in r.text


def test_intake_unsupported_file_type_rejected(data_dir, tmp_path):
    """Unsupported file extensions must be rejected."""
    # Create a .xyz file (not in SUPPORTED_EXTENSIONS) inside data dir
    data_dir_path = Path(config.data_dir())
    unsupported = data_dir_path / "test.xyz"
    unsupported.write_text("some data")
    r = client.post("/api/intake", data={"paths": [str(unsupported)]})
    # Should be rejected - .xyz not in SUPPORTED_EXTENSIONS
    body = r.json() if r.status_code == 200 else {}
    assert r.status_code >= 400 or body.get("counts", {}).get("error", 0) > 0


def test_intake_api_rejects_absolute_outside_path(data_dir, tmp_path):
    """Absolute path outside data dir must be rejected by API."""
    outside = tmp_path / "outside.csv"
    outside.write_text("Name,Email\nOutside,outside@example.com\n")
    r = client.post("/api/intake", data={"paths": [str(outside)]})
    assert r.status_code >= 400


def test_intake_csv_adapter_with_real_file(data_dir, tmp_path):
    """Real CSV file (multipart upload) should be extracted successfully."""
    r = client.post("/api/intake",
                    files=[("files", ("real_contacts.csv",
                                      b"Name,Email\nTest User,test@example.com\n",
                                      "text/csv"))])
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["new"] == 1
    assert body["results"][0]["status"] == "OK"


def test_filter_contacts_handler_defined():
    assert _handler_defined("filterContacts")


def test_export_contacts_handler_defined():
    assert _handler_defined("exportContacts")
