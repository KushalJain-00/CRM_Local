import asyncio
import shutil
from pathlib import Path

import config
import db
import pipeline

SAMPLE_EML = """From: Vikram Shah <vikram@example.com>
To: sales@acme.com
Subject: Quote request
Date: Mon, 02 Mar 2026 10:00:00 +0530
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

Please send the quotation.

Regards,
Vikram Shah
Beta LLP
+91 98123 45678
Mumbai
"""


def _setup(tmp_path, monkeypatch):
    crm_dir = tmp_path / "crm"
    eml_dir = tmp_path / "eml"
    crm_dir.mkdir()
    eml_dir.mkdir()
    cfg = config.load()
    cfg.update({"crm_dir": str(crm_dir), "eml_dir": str(eml_dir), "chain": []})
    config.save(cfg)
    return crm_dir, eml_dir


def test_scan_processes_eml_and_pushes_to_crm(data_dir, tmp_path, monkeypatch):
    crm_dir, eml_dir = _setup(tmp_path, monkeypatch)
    (eml_dir / "a.eml").write_text(SAMPLE_EML, "utf-8")
    (crm_dir / "contacts.csv").write_text(
        "Name,Email,Phone\nAsha Rao,asha@example.com,9876543210\n", "utf-8"
    )

    result = asyncio.run(pipeline.scan("all"))
    assert result["ok"] is True
    counts = db.counts()
    # D-007: intake/scan stages; canonical contacts are written only at approval.
    assert counts["emails"] == 1
    assert counts["crm"] == 0
    assert counts["staged"] == 2

    con = db.connect("eml")
    row = con.execute(
        "SELECT * FROM staged_contacts WHERE source_type = 'eml'").fetchone()
    assert row["email_key"] == "vikram@example.com"
    assert row["import_status"] == "NOT_IMPORTED"
    links = con.execute("SELECT * FROM email_staged_links").fetchall()
    assert len(links) == 1
    con.close()


def test_second_scan_is_a_no_op(data_dir, tmp_path, monkeypatch):
    _, eml_dir = _setup(tmp_path, monkeypatch)
    (eml_dir / "a.eml").write_text(SAMPLE_EML, "utf-8")

    asyncio.run(pipeline.scan("all"))
    before = db.counts()
    assert pipeline.pending_counts() == {"crm": 0, "eml": 0}

    result = asyncio.run(pipeline.scan("all"))
    assert result["stats"]["files"] == 0
    assert db.counts() == before


def test_eml_processed_in_date_order(data_dir, tmp_path, monkeypatch):
    _, eml_dir = _setup(tmp_path, monkeypatch)
    older = SAMPLE_EML.replace("Mon, 02 Mar 2026", "Mon, 01 Jan 2024")
    newer = SAMPLE_EML.replace("Mon, 02 Mar 2026", "Mon, 01 Jan 2026").replace(
        "vikram@example.com", "later@example.com"
    )
    (eml_dir / "z-newer.eml").write_text(newer, "utf-8")
    (eml_dir / "a-older.eml").write_text(older, "utf-8")

    paths = pipeline._pending(str(eml_dir), "eml", pipeline.EML_EXTS)
    assert [Path(p).name for p in paths] == ["a-older.eml", "z-newer.eml"]


def test_llm_fields_do_not_override_local(data_dir, tmp_path, monkeypatch):
    _, eml_dir = _setup(tmp_path, monkeypatch)
    (eml_dir / "a.eml").write_text(SAMPLE_EML, "utf-8")

    async def fake_extract(chain, prompt, **kwargs):
        return {"name": "Vikram S Shah", "city": "Pune"}, "fake/model"

    import services.extract as extract_mod
    monkeypatch.setattr(extract_mod.llm, "extract", fake_extract)
    cfg = config.load()
    cfg["chain"] = [{"provider": "openrouter", "model": "x", "api_key": "k", "enabled": True}]
    config.save(cfg)

    asyncio.run(pipeline.scan("eml"))
    con = db.connect("eml")
    row = con.execute(
        "SELECT name, city FROM staged_contacts WHERE source_type = 'eml'").fetchone()
    con.close()
    assert row["name"] == "Vikram Shah"  # local wins (D-007)
    assert row["city"] == "Mumbai"  # local wins (D-007)


def test_missing_folder_is_reported_not_crashed(data_dir, tmp_path, monkeypatch):
    cfg = config.load()
    cfg.update({"crm_dir": str(tmp_path / "nope"), "eml_dir": "", "chain": []})
    config.save(cfg)
    result = asyncio.run(pipeline.scan("all"))
    assert result["ok"] is True
    assert result["stats"]["files"] == 0
