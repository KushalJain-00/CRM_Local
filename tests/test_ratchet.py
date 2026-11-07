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
@pytest.mark.xfail(
    reason="BUG-D009: bare dropped file names fail intake os.path.exists check (intake.py:42) — no upload transport exists yet",
    strict=True,
)
def test_api_intake_resolves_dropped_bare_filename(data_dir):
    r = client.post("/api/intake", json={"paths": ["dropped_contacts.csv"]})
    assert "file not found" not in r.text


# --- BUG-SEC-05: no path containment on /api/intake -------------------------
@pytest.mark.xfail(
    reason="BUG-SEC-05: /api/intake ingests any absolute path from the request body (app.py:231-239, intake.py:42) with no containment to configured dirs",
    strict=True,
)
def test_api_intake_refuses_paths_outside_data_dirs(data_dir, tmp_path):
    outside = tmp_path / "outside.csv"
    outside.write_text("Name,Email\nMallory Example,mallory@example.com\n", "utf-8")
    r = client.post("/api/intake", json={"paths": [str(outside)]})
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
    mode = stat.S_IMODE(config.config_path().stat().st_mode)
    assert mode == 0o600, oct(mode)


# --- BUG-SEC-13: ignore-list gaps ------------------------------------------
# FLIPPED: config.json / config.json.bak / data_backup/ now ignored
# (SECURITY_REVIEW.md SEC-13), so the marker is gone and coverage asserted.
def test_gitignore_covers_backups():
    gitignore = (ROOT / ".gitignore").read_text("utf-8")
    assert "data_backup" in gitignore


# --- BUG-D029: undefined frontend handlers ---------------------------------
# Static-content tests: these functions are referenced by inline handlers in
# index.html and defined nowhere; browser JS cannot be unit-tested here, so the
# reference-vs-definition mismatch in the static assets is the pinnable defect.


@pytest.mark.xfail(
    reason="BUG-D029-filterContacts: index.html calls filterContacts() but static/app.js defines no such function",
    strict=True,
)
def test_filter_contacts_handler_defined():
    assert _handler_defined("filterContacts")


@pytest.mark.xfail(
    reason="BUG-D029-exportContacts: index.html calls exportContacts() but static/app.js defines no such function",
    strict=True,
)
def test_export_contacts_handler_defined():
    assert _handler_defined("exportContacts")
