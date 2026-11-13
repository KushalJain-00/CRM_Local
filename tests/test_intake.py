# tests/test_intake.py — Intake tests

import asyncio

import config
import db
import intake

def _setup(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    config.data_dir = lambda: d
    db.init()
    crm_dir = tmp_path / "crm"
    eml_dir = tmp_path / "eml"
    crm_dir.mkdir()
    eml_dir.mkdir()
    config.save({"crm_dir": str(crm_dir), "eml_dir": str(eml_dir), "chain": [], "watch": False, "watch_interval": 30, "autostart": False, "theme": "light"})
    return crm_dir, eml_dir

def test_universal_intake_csv(tmp_path):
    crm_dir, eml_dir = _setup(tmp_path)
    (crm_dir / "contacts.csv").write_text("Name,Email,Phone\nAsha Rao,asha@example.com,9876543210\n", "utf-8")
    result = asyncio.run(intake.universal_intake([str(crm_dir / "contacts.csv")]))
    assert result["ok"] is True
    assert result["counts"]["new"] == 1
    assert result["results"][0]["status"] == "OK"
    assert result["results"][0]["adapter"] == "csv"

def test_universal_intake_empty():
    result = asyncio.run(intake.universal_intake([]))
    assert result["ok"] is True
    assert result["results"] == []
    assert result["counts"]["new"] == 0

def test_universal_intake_unsupported():
    result = asyncio.run(intake.universal_intake(["/tmp/nonexistent.xyz"]))
    assert result["ok"] is True
    assert result["results"][0]["status"] == "ERROR"