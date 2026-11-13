# tests/test_extract_parity.py — intake (upload) and pipeline (folder scan)
# must stage byte-identical contacts through the shared extraction core.
import asyncio
import sqlite3

import pytest

import config
import db
import intake
import pipeline

STAGED_COLS = (
    "name email email_secondary phone_primary phone_secondary company designation"
    " address city pincode website whatsapp to_emails cc_emails bcc_emails"
    " email_key phone_key name_key company_key website_key"
    " validation_status review_status dedup_status source_type source_file"
).split()

LEDGER_COLS = ("status", "contacts_found")


def _dump(con, sql, cols):
    rows = con.execute(sql).fetchall()
    return [tuple(r) for r in rows]


def _staged_dump(con):
    return _dump(con, f"SELECT {', '.join(STAGED_COLS)} FROM staged_contacts ORDER BY id",
                 STAGED_COLS)


def _ledger_dump(con):
    return _dump(con, """SELECT status, contacts_found
                         FROM processed_files ORDER BY status, contacts_found""",
                 LEDGER_COLS)


def _fresh_env(tmp_path, name):
    data_dir = tmp_path / name
    data_dir.mkdir(parents=True)
    config.data_dir = lambda: data_dir
    crm_dir = tmp_path / (name + "_crm")
    eml_dir = tmp_path / (name + "_eml")
    crm_dir.mkdir(); eml_dir.mkdir()
    config.save({"crm_dir": str(crm_dir), "eml_dir": str(eml_dir),
                 "chain": [], "watch": False, "watch_interval": 30,
                 "autostart": False, "theme": "light", "reliability": {}, "prompts": {}})
    db.init()
    return crm_dir, eml_dir


def _run_intake(tmp_path, filename, payload):
    crm_dir, _ = _fresh_env(tmp_path, "intake")
    f = crm_dir / filename
    f.write_bytes(payload if isinstance(payload, bytes) else payload.encode())
    result = asyncio.run(intake.universal_intake([str(f)], chain=[]))
    assert result["ok"] is True
    con = db.connect("crm")
    staged, ledger = _staged_dump(con), _ledger_dump(con)
    con.close()
    return staged, ledger


def _run_scan(tmp_path, filename, payload):
    crm_dir, eml_dir = _fresh_env(tmp_path, "scan")
    ext = filename.rsplit(".", 1)[-1].lower()
    target = eml_dir if ext == "eml" else crm_dir
    f = target / filename
    f.write_bytes(payload if isinstance(payload, bytes) else payload.encode())
    result = asyncio.run(pipeline.scan("eml" if ext == "eml" else "crm"))
    assert result["ok"] is True
    assert result["stats"]["errors"] == 0
    con = db.connect("crm")
    staged, ledger = _staged_dump(con), _ledger_dump(con)
    con.close()
    return staged, ledger


_EML = b"""From: Priya Nair <priya@acme.in>
To: me@mycorp.com
Cc: boss@mycorp.com
Subject: pricing
Date: Mon, 1 Jun 2026 10:00:00 +0530
Content-Type: text/plain; charset=utf-8

Hi,
Best regards,
Priya Nair
+91 98123 45678
Acme Corp
"""

_EML_NO_IDENTITY = b"""Subject: hello
Content-Type: text/plain; charset=utf-8

hello world, nothing here identifies anyone
"""

_FILES = {
    "table_good.csv": "Name,Email,Company\nAsha Rao,asha@example.com,Acme\nNo One,"
                      "nobody@example.com,Beta\n",
    "sparse.csv": "Phone,Other,Label\n9876543210,x,y\n",
    "eml_basic.eml": _EML,
    "eml_no_identity.eml": _EML_NO_IDENTITY,
}


@pytest.mark.parametrize("filename", sorted(_FILES))
def test_intake_and_scan_stage_identically(tmp_path, filename):
    payload = _FILES[filename]
    staged_a, ledger_a = _run_intake(tmp_path / "a", filename, payload)
    staged_b, ledger_b = _run_scan(tmp_path / "b", filename, payload)
    assert staged_a == staged_b
    assert ledger_a == ledger_b
