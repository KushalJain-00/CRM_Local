"""Phase-1 staged-contact migration train (D-030) — P0-1 migration verification.

All tests are hermetic: fixtures are built under tmp_path, the live DB
(~/.crm_local/crm.db) is never opened for writing, and no test can trigger a
migration on it (the D-030 gate in run_migrations is itself tested below).
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402


# ── legacy (pre-migration) fixture ──────────────────────────────────────────

_LEGACY_SCHEMA = """
CREATE TABLE contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER, extraction_run_id INTEGER,
  name TEXT, email_primary TEXT, email_secondary TEXT,
  phone_primary TEXT, phone_secondary TEXT,
  address TEXT, city TEXT, pincode TEXT, website TEXT,
  position TEXT, designation TEXT, whatsapp TEXT,
  company TEXT, notes TEXT, created_at TEXT, updated_at TEXT, deleted_at TEXT
);
CREATE TABLE companies (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, address TEXT,
  city TEXT, pincode TEXT, website TEXT, industry TEXT, product TEXT,
  created_at TEXT, updated_at TEXT);
CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
  table_name TEXT, row_index INTEGER, data TEXT, created_at TEXT);
CREATE TABLE eml_emails (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sender_name TEXT, sender_email TEXT, to_emails TEXT, cc_emails TEXT, bcc_emails TEXT,
  subject TEXT, body TEXT, date TEXT, file_name TEXT, file_path TEXT, file_size INTEGER,
  file_hash TEXT, imported_at TEXT, user_id INTEGER, msg_id TEXT, in_reply_to TEXT,
  references_header TEXT, thread_root INTEGER, thread_depth INTEGER, thread_position INTEGER,
  is_read INTEGER DEFAULT 0, read_at TEXT
);
CREATE TABLE eml_contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_email_id INTEGER,
  name TEXT, email TEXT, phone_primary TEXT, phone_secondary TEXT,
  company TEXT, designation TEXT,
  address TEXT, city TEXT, pincode TEXT, website TEXT,
  dedup_status TEXT DEFAULT 'NEW',
  pushed_to_crm INTEGER DEFAULT 0, crm_contact_id INTEGER,
  source_file TEXT, to_emails TEXT, cc_emails TEXT, bcc_emails TEXT,
  field_origin TEXT, email_key TEXT, phone_key TEXT,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE processed_files (path TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT,
  status TEXT, total_records INTEGER DEFAULT 0, imported INTEGER DEFAULT 0,
  skipped INTEGER DEFAULT 0, source_type TEXT, sha256 TEXT);
CREATE TABLE extraction_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
  source_file TEXT, started_at TEXT, finished_at TEXT, status TEXT,
  total_rows INTEGER, imported INTEGER, skipped INTEGER, errors TEXT);
CREATE TABLE _migration_log (version INTEGER PRIMARY KEY, name TEXT NOT NULL,
  applied_at TEXT NOT NULL, rollback_sql TEXT, checksum TEXT);
INSERT INTO _migration_log (version, name, applied_at)
VALUES (1, 'unified_schema', '2026-11-06 14:14:55');
"""

_LEGACY_SEED = [
    # contacts: Alice needs position←designation backfill; keys must be computed
    ("INSERT INTO contacts (name,email_primary,phone_primary,position,designation,"
     " created_at,updated_at) VALUES ('Alice','alice@x.com','111',NULL,'Manager','new','0')"),
    ("INSERT INTO contacts (name,email_primary,created_at,updated_at)"
     " VALUES ('Bob','bob@x.com','new','0')"),
    # emails: one with to/cc/bcc (receiver backfill), one empty
    ("INSERT INTO eml_emails (sender_name,sender_email,to_emails,cc_emails,bcc_emails,"
     " subject,date) VALUES ('S','s@a.com','alice@x.com, bob@x.com','cc@x.com','','Hi','2024-01-01')"),
    ("INSERT INTO eml_emails (sender_name,sender_email,to_emails,subject,date)"
     " VALUES ('S2','s2@a.com','','Yo','2024-01-02')"),
    # eml_contacts: phantom (pushed=1, no link), normal, and one with NULL
    # source_email_id — live DB has 1 NULL of 47, so links == rows-with-source
    ("INSERT INTO eml_contacts (email,phone_primary,name,company,designation,address,city,"
     " pincode,website,to_emails,cc_emails,bcc_emails,pushed_to_crm,crm_contact_id,"
     " source_email_id,email_key,phone_key,dedup_status,created_at,updated_at) VALUES"
     " ('alice@x.com','111','Alice','Acme','Manager','St 1','Pune','411001','www.acme.com',"
     " 'alice@x.com, bob@x.com','cc@x.com','',1,NULL,1,'alice@x.com','111','NEW','new','0')"),
    ("INSERT INTO eml_contacts (email,phone_primary,name,pushed_to_crm,crm_contact_id,"
     " source_email_id,email_key,phone_key,dedup_status,created_at,updated_at)"
     " VALUES ('bob@x.com','222','Bob',0,99,2,'bob@x.com','222','NEW','new','0')"),
    ("INSERT INTO eml_contacts (email,phone_primary,name,pushed_to_crm,crm_contact_id,"
     " source_email_id,email_key,phone_key,dedup_status,created_at,updated_at)"
     " VALUES ('carol@x.com','333','Carol',0,NULL,NULL,'carol@x.com','333','NEW','new','0')"),
]


def build_legacy_db(path, records_rows: int = 0) -> sqlite3.Connection:
    """Pre-migration DB in the live shape: no FK on contacts, no staging tables,
    no receiver cols, records present, _migration_log = [1] only."""
    con = sqlite3.connect(path)
    con.executescript(_LEGACY_SCHEMA)
    for stmt in _LEGACY_SEED:
        con.execute(stmt)
    for i in range(records_rows):
        con.execute(
            "INSERT INTO records (session_id,table_name,row_index,data,created_at)"
            " VALUES ('s1','Sheet1',?,'{}','2024-01-01')", (i,))
    con.commit()
    return con


@pytest.fixture()
def legacy_db(tmp_path):
    con = build_legacy_db(tmp_path / "legacy.db")
    yield con
    con.close()


def log_versions(con) -> list[int]:
    return [r[0] for r in con.execute("SELECT version FROM _migration_log ORDER BY version")]


# ── P0-1: order, idempotency, integrity ─────────────────────────────────────

def test_v2_v9_apply_in_order(data_dir):
    """Fresh DB applies the whole train in order with checksums recorded."""
    con = sqlite3.connect(data_dir / "crm.db")
    try:
        assert log_versions(con) == [1, 2, 3, 4, 5, 6, 9, 10]
        for v, name, applied_at, rollback, checksum in con.execute(
                "SELECT version,name,applied_at,rollback_sql,checksum FROM _migration_log"):
            if v == 1:
                continue  # pre-existing row has no checksum (live baseline)
            assert applied_at, f"v{v} missing applied_at"
            assert checksum and len(checksum) == 64, f"v{v} missing sha256 checksum"
            assert name
        # v7/v8 are RESERVED and must not appear
        assert 7 not in log_versions(con) and 8 not in log_versions(con)
    finally:
        con.close()


def test_migration_idempotent_rerun(data_dir, legacy_db):
    """Second run is a no-op; a wiped log re-runs without duplicating data."""
    fresh = sqlite3.connect(data_dir / "crm.db")
    try:
        assert db.run_migrations(fresh) == []
    finally:
        fresh.close()

    applied = db.run_migrations(legacy_db)
    assert applied == [2, 3, 4, 5, 6, 9, 10]
    assert db.run_migrations(legacy_db) == []
    staged = legacy_db.execute("SELECT COUNT(*) FROM staged_contacts").fetchone()[0]
    # wipe the log (simulates a lost log) → train re-runs, guards prevent dupes
    legacy_db.execute("DELETE FROM _migration_log WHERE version > 1")
    legacy_db.commit()
    assert db.run_migrations(legacy_db) == [2, 3, 4, 5, 6, 9, 10]
    assert legacy_db.execute("SELECT COUNT(*) FROM staged_contacts").fetchone()[0] == staged
    assert legacy_db.execute("SELECT COUNT(*) FROM email_staged_links").fetchone()[0] == 2


def test_integrity_and_fk_check_clean(data_dir, legacy_db):
    """P0-1: PRAGMA integrity_check = ok and foreign_key_check empty after the
    train, on both a fresh DB and a migrated legacy DB."""
    db.run_migrations(legacy_db)
    for con in (legacy_db, sqlite3.connect(data_dir / "crm.db")):
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []


# ── P0-1: v6 rebuild safety ─────────────────────────────────────────────────

def test_v6_rebuild_preserves_row_count_and_columns(legacy_db):
    """P0-1: the contacts rebuild preserves every row/id/column, adds the real
    company FK + dedup keys + deleted_at, and backfills position (D-016)."""
    before_cols = {r[1] for r in legacy_db.execute("PRAGMA table_info(contacts)")}
    before_ids = {r[0] for r in legacy_db.execute("SELECT id FROM contacts")}
    before_rows = legacy_db.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]

    db.run_migrations(legacy_db)

    after_info = legacy_db.execute("PRAGMA table_info(contacts)").fetchall()
    after_cols = {r[1] for r in after_info}
    assert before_cols <= after_cols, f"columns lost: {before_cols - after_cols}"
    assert {"name_key", "company_key", "website_key", "deleted_at"} <= after_cols
    assert legacy_db.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == before_rows
    assert {r[0] for r in legacy_db.execute("SELECT id FROM contacts")} == before_ids

    fk = {(r[2], r[3]) for r in legacy_db.execute("PRAGMA foreign_key_list(contacts)")}
    assert ("companies", "company_id") in fk, "D-016: real company FK missing"

    # position backfilled from designation, designation kept
    alice = legacy_db.execute(
        "SELECT position, designation FROM contacts WHERE name='Alice'").fetchone()
    assert alice == ("Manager", "Manager")
    # keys computed
    assert legacy_db.execute(
        "SELECT name_key FROM contacts WHERE name='Alice'").fetchone()[0] == "alice"
    # indexes recreated (8 base + 6 §4.2 C)
    idx = {r[0] for r in legacy_db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='contacts'")}
    assert {"idx_contacts_name_key", "idx_contacts_company_key",
            "idx_contacts_website_key", "idx_contacts_company_id"} <= idx


# ── P0-1: step-0 backup and rollback ────────────────────────────────────────

def test_step0_backup_created_before_migration(tmp_path):
    """P0-1: the step-0 backup (sqlite3 backup API) captures the PRE-migration
    state; migrating afterwards leaves the backup untouched."""
    legacy_path = tmp_path / "live_like.db"
    con = build_legacy_db(legacy_path)
    con.close()

    backup_path = tmp_path / "data_backup" / "crm.db.step0-test"
    out = db.backup_database(backup_path, legacy_path)
    assert out == str(backup_path)

    con = sqlite3.connect(legacy_path)
    db.run_migrations(con)  # migrate AFTER the backup
    con.close()

    bak = sqlite3.connect(backup_path)
    try:
        # pre-state: records present, no staging, no FK, log = [1]
        assert bak.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='records'").fetchone()[0] == 1
        assert bak.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='staged_contacts'").fetchone()[0] == 0
        assert bak.execute("PRAGMA foreign_key_list(contacts)").fetchall() == []
        assert log_versions(bak) == [1]
        assert bak.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        bak.close()


def test_rollback_restores_backup(tmp_path):
    """P0-1: restore_database(backup) puts the pre-migration state back."""
    legacy_path = tmp_path / "live_like.db"
    con = build_legacy_db(legacy_path)
    con.close()
    backup_path = tmp_path / "step0.db"
    db.backup_database(backup_path, legacy_path)

    con = sqlite3.connect(legacy_path)
    db.run_migrations(con)
    assert con.execute("SELECT COUNT(*) FROM staged_contacts").fetchone()[0] == 3
    con.close()

    db.restore_database(backup_path, legacy_path)  # rollback path

    con = sqlite3.connect(legacy_path)
    try:
        assert log_versions(con) == [1]
        # pre-migration state: no staging tables at all (they came with v3)
        assert con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='staged_contacts'").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 2
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()


# ── backfill correctness (v4/v5, D-015, D-022) ──────────────────────────────

def test_eml_backfill_preserves_all_fields(legacy_db):
    db.run_migrations(legacy_db)
    row = legacy_db.execute(
        "SELECT source_type,name,email,phone_primary,company,designation,address,city,"
        " pincode,website,to_emails,cc_emails,bcc_emails,review_status,dedup_status,"
        " import_status,pushed_to_crm FROM staged_contacts WHERE name='Alice'").fetchone()
    (stype, name, email, phone, company, desig, addr, city, pin, site,
     to_, cc, bcc, review, dedup, imp, pushed) = row
    assert stype == "eml"  # lowercase per task spec (doc §4.3 says 'EML' — deviation)
    assert (name, email, phone, company, desig) == ("Alice", "alice@x.com", "111", "Acme", "Manager")
    assert (addr, city, pin, site) == ("St 1", "Pune", "411001", "www.acme.com")
    assert (to_, cc, bcc) == ("alice@x.com, bob@x.com", "cc@x.com", "")
    assert (review, dedup, imp) == ("NEW", "NOT_CHECKED", "NOT_IMPORTED")
    assert pushed == 1
    # garbage source timestamps are preserved inside raw_source_data
    raw = legacy_db.execute(
        "SELECT raw_source_data FROM staged_contacts WHERE name='Alice'").fetchone()[0]
    assert '"created_at": "new"' in raw and '"updated_at": "0"' in raw
    # eml_contacts itself is never touched
    assert legacy_db.execute(
        "SELECT pushed_to_crm, crm_contact_id FROM eml_contacts WHERE name='Alice'"
    ).fetchone() == (1, None)


def test_d015_phantom_rows_warned_never_auto_imported(legacy_db):
    """D-015: pushed_to_crm=1 without a surviving link → explicit warning,
    import_status stays NOT_IMPORTED; no auto-link by email_key."""
    db.run_migrations(legacy_db)
    alice = legacy_db.execute(
        "SELECT import_status, validation_warnings, crm_contact_id"
        " FROM staged_contacts WHERE name='Alice'").fetchone()
    assert alice[0] == "NOT_IMPORTED"
    assert alice[1] and "pushed_to_crm set before link existed" in alice[1]
    assert alice[2] is None
    # Bob's eml row has crm_contact_id=99 which does not resolve → FK-safe NULL
    bob = legacy_db.execute(
        "SELECT crm_contact_id, import_status FROM staged_contacts WHERE name='Bob'").fetchone()
    assert bob == (None, "NOT_IMPORTED")
    # every eml row keeps its own warning invariant: no un-warned phantoms
    un_warned = legacy_db.execute(
        "SELECT COUNT(*) FROM staged_contacts WHERE source_type='eml'"
        " AND pushed_to_crm=1 AND crm_contact_id IS NULL"
        " AND (validation_warnings IS NULL OR validation_warnings NOT LIKE '%pushed_to_crm%')"
    ).fetchone()[0]
    assert un_warned == 0
    # eml_contacts.pushed_to_crm is history — never rewritten
    assert legacy_db.execute(
        "SELECT COUNT(*) FROM eml_contacts WHERE pushed_to_crm=1").fetchone()[0] == 1


def test_email_staged_links_created(legacy_db):
    db.run_migrations(legacy_db)
    # 3 staged eml rows, but Carol has source_email_id NULL (live: 1 of 47) → 2 links
    links = legacy_db.execute(
        "SELECT email_id, staged_contact_id FROM email_staged_links ORDER BY email_id").fetchall()
    assert links == [(1, 1), (2, 2)]
    dangling = legacy_db.execute(
        "SELECT COUNT(*) FROM staged_contacts WHERE source_email_id IS NOT NULL"
        " AND source_email_id NOT IN (SELECT id FROM eml_emails)").fetchone()[0]
    assert dangling == 0


def test_receiver_columns_added_and_backfilled(legacy_db):
    """D-022: v2 adds receiver_name/receiver_email; backfill mirrors
    eml_processor.parse_eml_bytes (To+Cc+Bcc, ', '-joined)."""
    db.run_migrations(legacy_db)
    r1, r2 = legacy_db.execute(
        "SELECT id, receiver_name, receiver_email FROM eml_emails ORDER BY id").fetchall()
    assert r1[1] is None  # display names were never stored
    assert r1[2] == "alice@x.com, bob@x.com, cc@x.com"
    assert r2[2] in (None, "")  # empty to/cc/bcc → stays empty
    idx = {r[0] for r in legacy_db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='eml_emails'")}
    assert "idx_eml_emails_receiver_email" in idx


def test_records_dropped_when_empty_kept_when_populated(tmp_path):
    """D-017: `records` is dropped only when it exists AND has zero rows."""
    empty = build_legacy_db(tmp_path / "empty.db", records_rows=0)
    db.run_migrations(empty)
    assert empty.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='records'").fetchone()[0] == 0
    empty.close()

    full = build_legacy_db(tmp_path / "full.db", records_rows=3)
    db.run_migrations(full)
    assert full.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 3  # kept, untouched
    full.close()


# ── staged schema CHECK enums ───────────────────────────────────────────────

def test_staged_check_enums_enforce(data_dir):
    con = sqlite3.connect(data_dir / "crm.db")
    try:
        base = ("INSERT INTO staged_contacts (name, source_type, source_file_id,"
                " review_status, dedup_status, import_status, validation_status)"
                " VALUES ('X', ?, NULL, ?, ?, ?, 'UNVALIDATED')")
        bad = [
            ("EML", "NEW", "NOT_CHECKED", "NOT_IMPORTED"),       # uppercase source_type
            ("docx", "NEW", "NOT_CHECKED", "NOT_IMPORTED"),      # unknown source_type
            ("eml", "NOPE", "NOT_CHECKED", "NOT_IMPORTED"),      # bad review_status
            ("eml", "NEW", "WHATEVER", "NOT_IMPORTED"),          # bad dedup_status
            ("eml", "NEW", "NOT_CHECKED", "IMPORTED"),           # bad import_status
            ("eml", "NEW", "NOT_CHECKED", "NOT_IMPORTED"),       # valid → must pass
        ]
        for i, params in enumerate(bad):
            if i == len(bad) - 1:
                con.execute(base, params)
                continue
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(base, params)
        con.rollback()
    finally:
        con.close()


# ── P0-1: v7 deferred (replaces test_v7_view_returns_47) ────────────────────

def test_v7_view_deferred_eml_contacts_stays_physical(data_dir):
    """Phase 1 must NOT convert eml_contacts to a VIEW (v7), add FTS5 (v8), or
    log those versions — they belong to Phase 2 / Phase 5."""
    con = sqlite3.connect(data_dir / "crm.db")
    try:
        kind = con.execute("SELECT type FROM sqlite_master WHERE name='eml_contacts'").fetchone()
        assert kind == ("table",), "v7 must not run in Phase 1"
        assert con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='view'").fetchone()[0] == 0
        fts = con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name GLOB 'contacts_fts*'").fetchone()[0]
        assert fts == 0, "v8 FTS5 is Phase 5"
        versions = log_versions(con)
        assert 7 not in versions and 8 not in versions
        # the table is still directly readable with its rows intact
        assert con.execute("SELECT COUNT(*) FROM eml_contacts").fetchone()[0] == 0  # fresh DB
    finally:
        con.close()


# ── D-030 live-DB gate ──────────────────────────────────────────────────────

def test_live_db_gate_blocks_without_override(tmp_path, monkeypatch, capsys):
    """The canonical live path is never migrated by a plain run_migrations call:
    it returns [] and warns on stderr unless CRM_APPLY_MIGRATIONS=1 / force=True."""
    live_like = tmp_path / "crm.db"
    con = build_legacy_db(live_like)
    monkeypatch.setattr(db, "_live_db_file", lambda: str(live_like))

    assert db.run_migrations(con) == []
    err = capsys.readouterr().err
    assert "CRM_APPLY_MIGRATIONS" in err and "2, 3, 4" in err
    assert log_versions(con) == [1]  # nothing applied

    # env override applies the train
    monkeypatch.setenv("CRM_APPLY_MIGRATIONS", "1")
    assert db.run_migrations(con) == [2, 3, 4, 5, 6, 9, 10]
    monkeypatch.delenv("CRM_APPLY_MIGRATIONS")

    # force=True applies too (fresh legacy, wiped log)
    live2 = tmp_path / "crm2.db"
    con2 = build_legacy_db(live2)
    monkeypatch.setattr(db, "_live_db_file", lambda: str(live2))
    assert db.run_migrations(con2, force=True) == [2, 3, 4, 5, 6, 9, 10]
    con2.close()
    con.close()


def test_live_db_file_is_canonical_home_path():
    """The gate target is the canonical production path, resolved at call time."""
    expected = str((Path.home() / ".crm_local" / "crm.db").resolve())
    assert db._live_db_file() == expected


# ── D-022 writer: insert_email persists receiver fields ─────────────────────

def test_insert_email_persists_receiver_fields(data_dir):
    class Parsed:
        subject = "Hi"
        date = "2024-01-01"
        sender_name = "S"
        sender_email = "s@a.com"
        receiver_name = "R"
        receiver_email = "r@x.com"
        to_emails = "r@x.com"
        cc_emails = ""
        bcc_emails = ""
        body_text = "b"
        has_signature = False

    con = db.connect("crm")
    try:
        eid = db.insert_email(con, Parsed(), "/tmp/x.eml")
        con.commit()
        row = con.execute(
            "SELECT receiver_name, receiver_email FROM eml_emails WHERE id=?", (eid,)).fetchone()
        assert (row[0], row[1]) == ("R", "r@x.com")
    finally:
        con.close()
