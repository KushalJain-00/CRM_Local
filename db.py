# db.py — Unified SQLite store for CRM_Local (single database, all tables).
import hashlib
import json

import sqlite3
import os
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import config
from services.keys import name_key, company_key, website_key, phone_key, normalize_email

# Unified database: single file for all CRM + EML data (D-014)
_UNIFIED_DB = "crm.db"

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def connect(which: str = "crm") -> sqlite3.Connection:
    """Connect to the unified database. "which" is accepted for call-site
    compatibility and ignored (single SQLite file, D-014)."""
    con = sqlite3.connect(config.db_path("crm"), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init() -> None:
    """Initialize all tables in the unified database."""
    con = connect("crm")
    # Ensure existing tables have all columns before creating new ones
    _ensure_columns(con, "contacts", [
        ("company_id", "INTEGER"), ("email_secondary", "TEXT"), ("phone_secondary", "TEXT"),
        ("phone_country", "TEXT DEFAULT 'IN'"), ("whatsapp", "TEXT"), ("position", "TEXT"),
        ("files", "TEXT"), ("products_misc", "TEXT"), ("source_file", "TEXT"),
        ("source_row", "INTEGER"), ("extraction_run_id", "INTEGER"), ("field_origin", "TEXT"),
        ("email_key", "TEXT"), ("phone_key", "TEXT"), ("created_at", "TEXT"), ("updated_at", "TEXT"),
    ])
    _ensure_columns(con, "companies", [
        ("address", "TEXT"), ("pincode", "TEXT"), ("website", "TEXT"),
        ("industry", "TEXT"), ("product", "TEXT"), ("created_at", "TEXT"), ("updated_at", "TEXT"),
    ])
    con.commit()
    # Now create all tables (IF NOT EXISTS)
    con.executescript(_SCHEMA_UNIFIED)
    con.commit()
    # Run data migration from old eml.db
    _migrate(con)
    con.commit()
    # Staged-contact migration train (D-030 Phase 1). The canonical live DB is
    # gated inside run_migrations: it is applied only by the explicit gated
    # step (CRM_APPLY_MIGRATIONS=1 / force=True), never by a stray app start.
    run_migrations(con)
    con.commit()
    con.close()

_SCHEMA_UNIFIED = """
-- CRM tables
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT, address TEXT, city TEXT, pincode TEXT, website TEXT,
  industry TEXT, product TEXT,
  created_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(name);
CREATE INDEX IF NOT EXISTS idx_companies_city ON companies(city);

CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
  name TEXT, email_primary TEXT, email_secondary TEXT,
  phone_primary TEXT, phone_secondary TEXT,
  phone_country TEXT DEFAULT 'IN',
  company TEXT, designation TEXT, address TEXT, city TEXT, pincode TEXT, website TEXT,
  whatsapp TEXT, position TEXT, files TEXT, products_misc TEXT,
  source_file TEXT, source_row INTEGER, extraction_run_id INTEGER,
  field_origin TEXT, email_key TEXT, phone_key TEXT,
  created_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_contacts_company_id ON contacts(company_id);
CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name);
CREATE INDEX IF NOT EXISTS idx_contacts_email_primary ON contacts(email_primary);
CREATE INDEX IF NOT EXISTS idx_contacts_email_secondary ON contacts(email_secondary);
CREATE INDEX IF NOT EXISTS idx_contacts_phone_primary ON contacts(phone_primary);
CREATE INDEX IF NOT EXISTS idx_contacts_phone_secondary ON contacts(phone_secondary);
CREATE INDEX IF NOT EXISTS idx_contacts_email_key ON contacts(email_key);
CREATE INDEX IF NOT EXISTS idx_contacts_phone_key ON contacts(phone_key);

CREATE TABLE IF NOT EXISTS call_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contact_id INTEGER REFERENCES contacts(id) ON DELETE CASCADE,
  company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
  call_date TEXT, duration_minutes INTEGER, call_type TEXT, outcome TEXT,
  notes TEXT, next_action TEXT, next_action_date TEXT, created_by TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_call_logs_contact_id ON call_logs(contact_id);
CREATE INDEX IF NOT EXISTS idx_call_logs_company_id ON call_logs(company_id);
CREATE INDEX IF NOT EXISTS idx_call_logs_call_date ON call_logs(call_date);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL, name TEXT, provider_uid TEXT,
  last_login TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_provider_uid ON users(provider_uid);

CREATE TABLE IF NOT EXISTS session_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_name TEXT, sheet_name TEXT, upload_date TEXT, mapping TEXT,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  total_records INTEGER DEFAULT 0, imported INTEGER DEFAULT 0, skipped INTEGER DEFAULT 0,
  is_active INTEGER DEFAULT 1, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_session_data_user_id ON session_data(user_id);

-- `records` intentionally NOT created: dropped by migration v10 (D-017 —
-- staged_contacts.raw_source_data is the primary raw store).

-- EML tables (unified into same DB)
CREATE TABLE IF NOT EXISTS eml_emails (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_name TEXT, file_path TEXT, subject TEXT, date TEXT,
  sender_name TEXT, sender_email TEXT,
  to_emails TEXT, cc_emails TEXT, bcc_emails TEXT,
  body_text TEXT, has_signature INTEGER, signature_block TEXT, processed_at TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_eml_emails_sender_email ON eml_emails(sender_email);
CREATE INDEX IF NOT EXISTS idx_eml_emails_date ON eml_emails(date);

CREATE TABLE IF NOT EXISTS eml_contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_email_id INTEGER REFERENCES eml_emails(id) ON DELETE CASCADE,
  name TEXT, email TEXT, phone_primary TEXT, phone_secondary TEXT,
  company TEXT, designation TEXT, address TEXT, city TEXT, pincode TEXT, website TEXT,
  dedup_status TEXT, pushed_to_crm INTEGER DEFAULT 0,
  crm_contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
  source_file TEXT, to_emails TEXT, cc_emails TEXT, bcc_emails TEXT,
  field_origin TEXT, email_key TEXT, phone_key TEXT,
  created_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_eml_contacts_source_email_id ON eml_contacts(source_email_id);
CREATE INDEX IF NOT EXISTS idx_eml_contacts_crm_contact_id ON eml_contacts(crm_contact_id);
CREATE INDEX IF NOT EXISTS idx_eml_contacts_email ON eml_contacts(email);
CREATE INDEX IF NOT EXISTS idx_eml_contacts_email_key ON eml_contacts(email_key);
CREATE INDEX IF NOT EXISTS idx_eml_contacts_phone_key ON eml_contacts(phone_key);

-- Shared tables
CREATE TABLE IF NOT EXISTS processed_files (
  path TEXT PRIMARY KEY, size INTEGER, mtime REAL, status TEXT, detail TEXT,
  contacts_found INTEGER DEFAULT 0, processed_at TEXT
);

CREATE TABLE IF NOT EXISTS extraction_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  started_at TEXT, completed_at TEXT, status TEXT DEFAULT 'running',
  files_processed INTEGER DEFAULT 0, contacts_found INTEGER DEFAULT 0,
  error TEXT, config_snapshot TEXT
);
CREATE INDEX IF NOT EXISTS idx_extraction_runs_user_id ON extraction_runs(user_id);

CREATE TABLE IF NOT EXISTS _migration_log (
  version INTEGER PRIMARY KEY, name TEXT NOT NULL,
  applied_at TEXT NOT NULL, rollback_sql TEXT, checksum TEXT
);
"""

def _migrate(con: sqlite3.Connection) -> None:
    """Run idempotent migrations and data migration from old eml.db."""
    # Migration 1: ensure all columns exist (for existing crm.db)
    _ensure_columns(con, "contacts", [
        ("whatsapp", "TEXT"), ("products_misc", "TEXT"), ("source_file", "TEXT"),
        ("source_row", "INTEGER"), ("extraction_run_id", "INTEGER"),
        ("field_origin", "TEXT"), ("email_key", "TEXT"), ("phone_key", "TEXT"),
        ("email_secondary", "TEXT"), ("phone_secondary", "TEXT"),
        ("phone_country", "TEXT DEFAULT 'IN'"), ("designation", "TEXT"), ("position", "TEXT"),
        ("files", "TEXT"), ("created_at", "TEXT"), ("updated_at", "TEXT"),
    ])
    _ensure_columns(con, "companies", [
        ("address", "TEXT"), ("pincode", "TEXT"), ("website", "TEXT"),
        ("industry", "TEXT"), ("product", "TEXT"),
        ("created_at", "TEXT"), ("updated_at", "TEXT"),
    ])
    _ensure_columns(con, "eml_contacts", [
        ("field_origin", "TEXT"), ("email_key", "TEXT"), ("phone_key", "TEXT"),
        ("crm_contact_id", "INTEGER"),
    ])

    # Migration 2: migrate data from old eml.db if it exists
    _migrate_eml_data(con)

    # Record migration
    try:
        con.execute("INSERT OR IGNORE INTO _migration_log (version, name, applied_at) VALUES (1, 'unified_schema', datetime('now'))")
    except Exception:
        pass

def _ensure_columns(con: sqlite3.Connection, table: str, columns: list[tuple[str, str]]) -> None:
    """Add columns to a table if they don't exist (idempotent)."""
    try:
        existing = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return
    for col_name, col_type in columns:
        if col_name not in existing:
            try:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

def _migrate_eml_data(con: sqlite3.Connection) -> None:
    """Migrate data from old eml.db into the unified DB (idempotent)."""
    import config as _config
    eml_path = _config.db_path("eml")
    if not os.path.exists(eml_path):
        return
    # Check if migration already done
    try:
        count = con.execute("SELECT count(*) FROM eml_emails").fetchone()[0]
        if count > 0:
            return  # Already migrated
    except Exception:
        return

    try:
        src = sqlite3.connect(eml_path)
        src.row_factory = sqlite3.Row

        # Migrate emails
        try:
            rows = src.execute("SELECT * FROM emails").fetchall()
            for r in rows:
                con.execute("""
                    INSERT INTO eml_emails (file_name, file_path, subject, date, sender_name, sender_email,
                        to_emails, cc_emails, bcc_emails, body_text, has_signature, processed_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    r["file_name"], r["file_path"], r["subject"], r["date"],
                    r["sender_name"], r["sender_email"], r["to_emails"],
                    r["cc_emails"], r["bcc_emails"], r["body_text"],
                    r["has_signature"], r["processed_at"], now_iso(),
                ))
        except Exception as e:
            pass  # Table may not exist in old DB

        # Migrate eml_contacts
        try:
            rows = src.execute("SELECT * FROM eml_contacts").fetchall()
            for r in rows:
                con.execute("""
                    INSERT INTO eml_contacts (source_email_id, name, email, phone_primary, phone_secondary,
                        company, designation, address, city, pincode, website, dedup_status, pushed_to_crm,
                        source_file, email_key, phone_key, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    r["email_id"], r["name"], r["email_primary"], r["phone_primary"],
                    r["phone_secondary"], r["company"], r["designation"],
                    r["address"], r["city"], r["pincode"], r["website"],
                    "NEW", r["pushed"] if "pushed" in r.keys() else 0, r["source_file"],
                    normalize_email(r["email_primary"]) or None,
                    phone_key(r["phone_primary"]), r["created_at"], r["updated_at"],
                ))
        except Exception as e:
            pass

        # Migrate processed_files from eml.db (merge with crm processed_files)
        try:
            rows = src.execute("SELECT * FROM processed_files").fetchall()
            for r in rows:
                con.execute("""
                    INSERT OR IGNORE INTO processed_files (path, size, mtime, status, detail, contacts_found, processed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    r["path"], r["size"], r["mtime"], r["status"],
                    r["detail"], r["contacts_found"], r["processed_at"],
                ))
        except Exception:
            pass

        src.close()
        con.commit()
    except Exception as e:
        pass  # Migration is best-effort; original DBs are preserved

# ─── Staged-contact migration train (D-030, Phase 1) ─────────────────────────
# v2 receiver cols (D-022) · v3 staging + relationship/audit tables + CHECK
# enums · v4 backfill 47 eml_contacts rows into staged_contacts · v5 links +
# D-015 phantom warnings · v6 contacts rebuild (real company FK, dedup keys,
# soft-delete, position←designation) · v9 verify_and_log · v10 drop empty
# `records` (D-017). RESERVED, must NOT run in Phase 1: v7 eml_contacts→VIEW
# (Phase 2, same release as write-path redirection), v8 FTS5 (Phase 5).

CURRENT_MIGRATION_VERSION = 10
_MIGRATION_GATE_ENV = "CRM_APPLY_MIGRATIONS"   # set to "1" to apply on the live DB

class MigrationError(RuntimeError):
    """A migration failed and was rolled back; or a post-train check failed."""

def _live_db_file() -> str:
    """Canonical production DB path (D-030 gate anchor). Delegates to
    config so there is exactly one path implementation; deliberately NOT
    config.data_dir(), which tests legitimately monkeypatch."""
    return os.path.realpath(str(config.canonical_db_path()))

def _con_db_file(con: sqlite3.Connection) -> str:
    row = con.execute("PRAGMA database_list").fetchone()
    return os.path.realpath(row[2]) if row and row[2] else ""

# Identity keys live in services/keys.py — single implementation.

# §4.3 target DDL. Deviations from the doc, per D-030 task spec:
#  · source_type CHECK is LOWERCASE ('xlsx',…,'eml') — Phase-2 §4.2 view must match;
#  · to_emails/cc_emails/bcc_emails are real columns (the §4.2 view SELECTs them;
#    §4.3's CREATE TABLE omitted them) so all 17 eml_contacts fields survive v4.
_STAGING_DDL = [
    """CREATE TABLE IF NOT EXISTS staged_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_type TEXT NOT NULL
            CHECK (source_type IN ('xlsx','xls','csv','pdf','txt','eml')),
        source_file TEXT,
        source_file_id TEXT REFERENCES processed_files(path) ON DELETE SET NULL,
        source_row INTEGER,
        source_page INTEGER,
        source_sheet TEXT,
        source_email_id INTEGER REFERENCES eml_emails(id) ON DELETE SET NULL,
        name TEXT, email TEXT, phone_primary TEXT, phone_secondary TEXT,
        company TEXT, designation TEXT, address TEXT, city TEXT, pincode TEXT,
        website TEXT, whatsapp TEXT, position TEXT, files TEXT, products_misc TEXT,
        email_secondary TEXT,
        to_emails TEXT, cc_emails TEXT, bcc_emails TEXT,
        email_key TEXT, phone_key TEXT, name_key TEXT, company_key TEXT, website_key TEXT,
        raw_source_data TEXT, field_evidence TEXT, confidence REAL,
        extraction_run_id INTEGER REFERENCES extraction_runs(id) ON DELETE SET NULL,
        validation_status TEXT NOT NULL DEFAULT 'UNVALIDATED'
            CHECK (validation_status IN ('UNVALIDATED','VALID','INVALID')),
        validation_warnings TEXT,
        review_status TEXT NOT NULL DEFAULT 'NEW'
            CHECK (review_status IN ('NEW','NEEDS_REVIEW','READY','APPROVED','REJECTED','DISMISSED')),
        dedup_status TEXT NOT NULL DEFAULT 'NOT_CHECKED'
            CHECK (dedup_status IN ('NOT_CHECKED','UNIQUE','EXACT_DUPLICATE','PROBABLE_DUPLICATE','CONFLICT')),
        duplicate_candidate_ids TEXT,
        import_status TEXT NOT NULL DEFAULT 'NOT_IMPORTED'
            CHECK (import_status IN ('NOT_IMPORTED','NEW_CONTACT_CREATED','EXISTING_CONTACT_ENRICHED','IMPORT_FAILED')),
        crm_contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
        pushed_to_crm INTEGER NOT NULL DEFAULT 0,
        created_at TEXT, updated_at TEXT, reviewed_at TEXT
    )""",
    # status/keyset queues: composite (status, id) — §7.1 keyset pagination
    "CREATE INDEX IF NOT EXISTS idx_staged_review_id ON staged_contacts(review_status, id)",
    "CREATE INDEX IF NOT EXISTS idx_staged_dedup ON staged_contacts(dedup_status, id)",
    "CREATE INDEX IF NOT EXISTS idx_staged_import ON staged_contacts(import_status, id)",
    "CREATE INDEX IF NOT EXISTS idx_staged_email_key ON staged_contacts(email_key)",
    "CREATE INDEX IF NOT EXISTS idx_staged_phone_key ON staged_contacts(phone_key)",
    "CREATE INDEX IF NOT EXISTS idx_staged_name_key ON staged_contacts(name_key)",
    "CREATE INDEX IF NOT EXISTS idx_staged_company_key ON staged_contacts(company_key)",
    "CREATE INDEX IF NOT EXISTS idx_staged_website_key ON staged_contacts(website_key)",
    "CREATE INDEX IF NOT EXISTS idx_staged_source_email ON staged_contacts(source_email_id)",
    "CREATE INDEX IF NOT EXISTS idx_staged_crm_contact ON staged_contacts(crm_contact_id)",
    "CREATE INDEX IF NOT EXISTS idx_staged_source_file ON staged_contacts(source_type, source_file)",
    "CREATE INDEX IF NOT EXISTS idx_staged_extraction_run ON staged_contacts(extraction_run_id)",
    # email ↔ staged-contact M:N
    """CREATE TABLE IF NOT EXISTS email_staged_links (
        email_id INTEGER NOT NULL REFERENCES eml_emails(id) ON DELETE CASCADE,
        staged_contact_id INTEGER NOT NULL REFERENCES staged_contacts(id) ON DELETE CASCADE,
        created_at TEXT,
        PRIMARY KEY (email_id, staged_contact_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_email_staged_staged ON email_staged_links(staged_contact_id)",
    # canonical contact ↔ email M:N
    """CREATE TABLE IF NOT EXISTS contact_emails (
        contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        email_id INTEGER NOT NULL REFERENCES eml_emails(id) ON DELETE CASCADE,
        origin TEXT NOT NULL DEFAULT 'staged' CHECK (origin IN ('staged','sender','recipient')),
        created_at TEXT,
        PRIMARY KEY (contact_id, email_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_contact_emails_email ON contact_emails(email_id)",
    # merge audit — every merge recorded; nothing silently deleted (D-014)
    """CREATE TABLE IF NOT EXISTS contact_merges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        survivor_contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        merged_contact_id INTEGER,
        reason TEXT,
        merged_by TEXT,
        snapshot TEXT,
        created_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_contact_merges_survivor ON contact_merges(survivor_contact_id)",
    # field-level conflicts from local-wins enrichment (§6.3)
    """CREATE TABLE IF NOT EXISTS field_conflicts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
        field_name TEXT NOT NULL,
        existing_value TEXT, incoming_value TEXT,
        source_file TEXT, source_row INTEGER, extraction_run_id INTEGER,
        status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','RESOLVED')),
        resolved_value TEXT, resolved_at TEXT,
        created_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_field_conflicts_contact ON field_conflicts(contact_id, status)",
]

# v6 index set: the 8 from the base schema (db.py _SCHEMA_UNIFIED) + the 6 of
# §4.2 C. (column, sql) — skipped when a legacy/fixture table lacks the column.
_CONTACT_INDEXES = [
    ("company_id", "CREATE INDEX IF NOT EXISTS idx_contacts_company_id ON contacts(company_id)"),
    ("name", "CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name)"),
    ("email_primary", "CREATE INDEX IF NOT EXISTS idx_contacts_email_primary ON contacts(email_primary)"),
    ("email_secondary", "CREATE INDEX IF NOT EXISTS idx_contacts_email_secondary ON contacts(email_secondary)"),
    ("phone_primary", "CREATE INDEX IF NOT EXISTS idx_contacts_phone_primary ON contacts(phone_primary)"),
    ("phone_secondary", "CREATE INDEX IF NOT EXISTS idx_contacts_phone_secondary ON contacts(phone_secondary)"),
    ("email_key", "CREATE INDEX IF NOT EXISTS idx_contacts_email_key ON contacts(email_key)"),
    ("phone_key", "CREATE INDEX IF NOT EXISTS idx_contacts_phone_key ON contacts(phone_key)"),
    ("created_at", "CREATE INDEX IF NOT EXISTS idx_contacts_created_at ON contacts(created_at DESC)"),
    ("city", "CREATE INDEX IF NOT EXISTS idx_contacts_city ON contacts(city)"),
    ("pincode", "CREATE INDEX IF NOT EXISTS idx_contacts_pincode ON contacts(pincode)"),
    ("name_key", "CREATE INDEX IF NOT EXISTS idx_contacts_name_key ON contacts(name_key)"),
    ("company_key", "CREATE INDEX IF NOT EXISTS idx_contacts_company_key ON contacts(company_key)"),
    ("website_key", "CREATE INDEX IF NOT EXISTS idx_contacts_website_key ON contacts(website_key)"),
]

def _mig_v2_receiver_cols(con: sqlite3.Connection) -> None:
    """v2 (D-022, §4.2 A): receiver_name/receiver_email columns + backfill."""
    for ddl in ("ALTER TABLE eml_emails ADD COLUMN receiver_name TEXT",
                "ALTER TABLE eml_emails ADD COLUMN receiver_email TEXT"):
        try:
            con.execute(ddl)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
    con.execute("CREATE INDEX IF NOT EXISTS idx_eml_emails_receiver_email ON eml_emails(receiver_email)")
    # Backfill = To+Cc+Bcc joined with ", " exactly like eml_processor.parse_eml_bytes
    # (L117-131). Display names were never persisted, so receiver_name stays NULL.
    con.execute("""
        UPDATE eml_emails SET receiver_email = TRIM(
            TRIM(COALESCE(to_emails,''))
            || CASE WHEN TRIM(COALESCE(cc_emails,'')) <> '' THEN ', ' || TRIM(cc_emails) ELSE '' END
            || CASE WHEN TRIM(COALESCE(bcc_emails,'')) <> '' THEN ', ' || TRIM(bcc_emails) ELSE '' END
        , ' ,')
        WHERE (receiver_email IS NULL OR receiver_email = '')
          AND (TRIM(COALESCE(to_emails,'')) <> ''
               OR TRIM(COALESCE(cc_emails,'')) <> ''
               OR TRIM(COALESCE(bcc_emails,'')) <> '')
    """)

def _mig_v3_staging_tables(con: sqlite3.Connection) -> None:
    """v3 (§4.3): staged_contacts + relationship/audit tables + CHECK enums +
    status/keyset/dedup indexes; companies.website_key (§4.2 B)."""
    for stmt in _STAGING_DDL:
        con.execute(stmt)
    cols = {r[1] for r in con.execute("PRAGMA table_info(companies)")}
    if "website_key" not in cols:
        con.execute("ALTER TABLE companies ADD COLUMN website_key TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_companies_website_key ON companies(website_key)")

def _mig_v4_backfill_staged(con: sqlite3.Connection) -> None:
    """v4: copy every eml_contacts row into staged_contacts (source_type='eml'),
    preserving all 17 fields incl. to/cc/bcc; raw_source_data = JSON of the old
    row. Statuses: review_status='NEW', dedup_status='NOT_CHECKED' (old
    dedup_status kept inside raw_source_data), import_status='NOT_IMPORTED'
    for ALL rows (D-015: never auto-classify)."""
    if con.execute("SELECT COUNT(*) FROM staged_contacts WHERE source_type='eml'").fetchone()[0]:
        return  # already backfilled (e.g. log reset after a completed train)
    cur = con.execute("SELECT * FROM eml_contacts ORDER BY id")
    # zip(description) instead of dict(sqlite3.Row): run_migrations accepts any
    # connection, not just one with row_factory=Row
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    contact_ids = {r[0] for r in con.execute("SELECT id FROM contacts")}
    email_ids = {r[0] for r in con.execute("SELECT id FROM eml_emails")}
    for r in rows:
        d = dict(zip(cols, r))
        src_email = d.get("source_email_id")
        crm_id = d.get("crm_contact_id")
        con.execute("""
            INSERT INTO staged_contacts (
              source_type, source_file, source_email_id,
              name, email, phone_primary, phone_secondary, company, designation,
              address, city, pincode, website,
              to_emails, cc_emails, bcc_emails,
              email_key, phone_key, name_key, company_key, website_key,
              raw_source_data, field_evidence,
              review_status, dedup_status, import_status,
              crm_contact_id, pushed_to_crm, created_at, updated_at)
            VALUES ('eml', ?, ?,                      -- source_file, source_email_id
                    ?, ?, ?, ?, ?, ?,                 -- name..designation
                    ?, ?, ?, ?,                       -- address..website
                    ?, ?, ?,                          -- to/cc/bcc
                    ?, ?, ?, ?, ?,                    -- email_key..website_key
                    ?, ?,                             -- raw_source_data, field_evidence
                    'NEW', 'NOT_CHECKED', 'NOT_IMPORTED',
                    ?, ?, ?, ?)                       -- crm_contact_id, pushed, created, updated
        """, (
            d.get("source_file"),
            src_email if src_email in email_ids else None,
            d.get("name"), d.get("email"),
            d.get("phone_primary"), d.get("phone_secondary"),
            d.get("company"), d.get("designation"),
            d.get("address"), d.get("city"), d.get("pincode"), d.get("website"),
            d.get("to_emails"), d.get("cc_emails"), d.get("bcc_emails"),
            normalize_email(d.get("email")) or None,
            phone_key(d.get("phone_primary")),
            name_key(d.get("name")), company_key(d.get("company")), website_key(d.get("website")),
            json.dumps(d, ensure_ascii=False, default=str),
            d.get("field_origin"),
            crm_id if crm_id in contact_ids else None,
            d.get("pushed_to_crm") or 0,
            now_iso(), now_iso(),
        ))
    n = con.execute("SELECT COUNT(*) FROM staged_contacts WHERE source_type='eml'").fetchone()[0]
    if n != len(rows):
        raise MigrationError(f"v4: staged {n} rows != eml_contacts {len(rows)}")

def _mig_v5_backfill_links_status(con: sqlite3.Connection) -> None:
    """v5: email_staged_links (source_email_id, EXISTS-guarded) + D-015 phantom
    rows get an explicit validation warning; import_status stays NOT_IMPORTED —
    never auto-link via email_key even though matches exist (D-015 wins over
    §5 v5b). eml_contacts.pushed_to_crm is history and is never touched."""
    con.execute("""
        INSERT OR IGNORE INTO email_staged_links (email_id, staged_contact_id, created_at)
        SELECT s.source_email_id, s.id, datetime('now')
        FROM staged_contacts s
        WHERE s.source_type = 'eml' AND s.source_email_id IS NOT NULL
          AND EXISTS (SELECT 1 FROM eml_emails e WHERE e.id = s.source_email_id)
    """)
    con.execute("""
        UPDATE staged_contacts SET validation_warnings =
          CASE WHEN validation_warnings IS NULL OR validation_warnings = ''
            THEN json_array('pushed_to_crm set before link existed')
            ELSE json_insert(validation_warnings, '$[#]', 'pushed_to_crm set before link existed')
          END
        WHERE source_type = 'eml' AND pushed_to_crm = 1 AND crm_contact_id IS NULL
          AND (validation_warnings IS NULL OR validation_warnings = ''
               OR validation_warnings NOT LIKE '%pushed_to_crm set before link existed%')
    """)
    left = con.execute("""
        SELECT COUNT(*) FROM staged_contacts
        WHERE source_type = 'eml' AND pushed_to_crm = 1 AND crm_contact_id IS NULL
          AND (validation_warnings IS NULL OR validation_warnings = ''
               OR import_status <> 'NOT_IMPORTED')
    """).fetchone()[0]
    if left:
        raise MigrationError(f"v5: {left} phantom rows missing D-015 warning/status")

def _mig_v6_rebuild_contacts(con: sqlite3.Connection) -> None:
    """v6 (D-016): SQLite table rebuild of `contacts`. ALTER cannot add the
    missing company FK (live DB drifted), so: real FKs to companies and
    extraction_runs, dedup keys (§6.5), soft-delete column deleted_at (D-014),
    position backfilled from designation (§8 Q4; designation kept). Row count
    and id set must be identical; child rows survive because the runner holds
    foreign_keys=OFF for this migration (an implicit DELETE cascade/SET NULL
    during DROP would wipe call_logs / eml_contacts links)."""
    info = con.execute("PRAGMA table_info(contacts)").fetchall()
    old_cols = [r[1] for r in info]
    old_count = con.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    old_ids = {r[0] for r in con.execute("SELECT id FROM contacts")}

    fk_def = {
        "company_id": "company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL",
        "extraction_run_id": "extraction_run_id INTEGER REFERENCES extraction_runs(id) ON DELETE SET NULL",
    }
    defs = []
    for r in info:
        cname, ctype, notnull, dflt, pk = r[1], (r[2] or "TEXT"), r[3], r[4], r[5]
        if cname in fk_def:
            defs.append(fk_def[cname])
            continue
        if pk:
            d = f"{cname} {ctype} PRIMARY KEY"
            if ctype.upper() == "INTEGER":
                d += " AUTOINCREMENT"
        else:
            d = f"{cname} {ctype}"
            if notnull:
                d += " NOT NULL"
            if dflt is not None:
                d += f" DEFAULT {dflt}"
        defs.append(d)
    for cname in fk_def:  # legacy/fixture tables missing these entirely
        if cname not in old_cols:
            defs.append(fk_def[cname])
    defs += [c for c in ("name_key TEXT", "company_key TEXT", "website_key TEXT", "deleted_at TEXT")
             if c.split()[0] not in old_cols]
    con.execute("CREATE TABLE contacts_new (" + ", ".join(defs) + ")")
    con.execute(f"INSERT INTO contacts_new ({', '.join(old_cols)}) SELECT {', '.join(old_cols)} FROM contacts")

    if "designation" in old_cols:
        con.execute(
            "UPDATE contacts_new SET position = designation"
            " WHERE position IS NULL AND designation IS NOT NULL AND designation <> ''"
        )
    def _src(col: str) -> str:
        return col if col in old_cols else "NULL"
    for r in con.execute(
        f"SELECT id, {_src('name')} AS nm, {_src('company')} AS co, {_src('website')} AS ws"
        " FROM contacts_new"
    ).fetchall():
        con.execute(
            "UPDATE contacts_new SET name_key = ?, company_key = ?, website_key = ? WHERE id = ?",
            (name_key(r[1]), company_key(r[2]), website_key(r[3]), r[0]),
        )

    new_count = con.execute("SELECT COUNT(*) FROM contacts_new").fetchone()[0]
    new_ids = {r[0] for r in con.execute("SELECT id FROM contacts_new")}
    if new_count != old_count:
        raise MigrationError(f"v6: row count changed {old_count} -> {new_count}")
    if new_ids != old_ids:
        raise MigrationError(f"v6: id set changed, delta={old_ids ^ new_ids}")
    if "email_primary" in old_cols:
        a = con.execute("SELECT COUNT(*) FROM contacts WHERE email_primary IS NOT NULL AND email_primary <> ''").fetchone()[0]
        b = con.execute("SELECT COUNT(*) FROM contacts_new WHERE email_primary IS NOT NULL AND email_primary <> ''").fetchone()[0]
        if a != b:
            raise MigrationError(f"v6: email_primary values lost ({a} -> {b})")

    con.execute("DROP TABLE contacts")
    con.execute("ALTER TABLE contacts_new RENAME TO contacts")
    cols_now = {r[1] for r in con.execute("PRAGMA table_info(contacts)")}
    for col, sql in _CONTACT_INDEXES:
        if col in cols_now:
            con.execute(sql)

def _mig_v9_verify_and_log(con: sqlite3.Connection) -> None:
    """v9 (§5): structural verification of the train; the runner additionally
    runs PRAGMA integrity_check + foreign_key_check after the last migration."""
    eml_n = con.execute("SELECT COUNT(*) FROM eml_contacts").fetchone()[0]
    staged_n = con.execute("SELECT COUNT(*) FROM staged_contacts WHERE source_type='eml'").fetchone()[0]
    if staged_n != eml_n:
        raise MigrationError(f"v9: staged eml rows {staged_n} != eml_contacts {eml_n}")
    dangling = con.execute("""
        SELECT COUNT(*) FROM staged_contacts
        WHERE source_type='eml' AND source_email_id IS NOT NULL
          AND source_email_id NOT IN (SELECT id FROM eml_emails)
    """).fetchone()[0]
    if dangling:
        raise MigrationError(f"v9: {dangling} staged rows link to missing emails")
    phantom = con.execute("""
        SELECT COUNT(*) FROM staged_contacts
        WHERE source_type='eml' AND pushed_to_crm = 1 AND crm_contact_id IS NULL
          AND (validation_warnings IS NULL OR validation_warnings NOT LIKE '%D-015%'
               AND validation_warnings NOT LIKE '%pushed_to_crm set before link existed%')
    """).fetchone()[0]
    if phantom:
        raise MigrationError(f"v9: {phantom} phantom rows lack D-015 warning")
    eml_type = con.execute("SELECT type FROM sqlite_master WHERE name='eml_contacts'").fetchone()
    if not eml_type or eml_type[0] != "table":
        raise MigrationError("v9: eml_contacts must stay a physical table (v7 deferred)")
    if con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='view'").fetchone()[0]:
        raise MigrationError("v9: unexpected views present (v7 deferred)")
    if con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name GLOB 'contacts_fts*'").fetchone()[0]:
        raise MigrationError("v9: FTS5 objects present but v8 is deferred to Phase 5")

def _mig_v10_drop_records(con: sqlite3.Connection) -> None:
    """v10 (D-017): drop `records` ONLY if it exists and is empty. Repo-wide
    grep shows zero readers/writers; if ever non-empty, it is left in place."""
    try:
        n = con.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    except sqlite3.OperationalError:
        return  # already dropped / never created (fresh base schema)
    if n == 0:
        con.execute("DROP TABLE records")

class _Migration:
    def __init__(self, version: int, name: str, fn, rollback_sql: str | None = None,
                 fk_off: bool = False):
        self.version = version
        self.name = name
        self.fn = fn
        self.rollback_sql = rollback_sql
        self.fk_off = fk_off  # runner holds PRAGMA foreign_keys=OFF around fn

    def checksum(self) -> str:
        # Must work in frozen (PyInstaller PYZ) mode where inspect.getsource
        # cannot find .py sources. Content hash of the migration's identity,
        # stable across platforms and builds.
        payload = f"v{self.version}:{self.name}:{self.rollback_sql or ''}".encode()
        return hashlib.sha256(payload).hexdigest()

_MIGRATIONS: dict[int, _Migration] = {}

def _register(m: _Migration) -> _Migration:
    _MIGRATIONS[m.version] = m
    return m

_register(_Migration(2, "eml_emails_receiver_cols", _mig_v2_receiver_cols,
    rollback_sql="ALTER TABLE eml_emails DROP COLUMN receiver_name; "
                 "ALTER TABLE eml_emails DROP COLUMN receiver_email; "
                 "DROP INDEX idx_eml_emails_receiver_email"))
_register(_Migration(3, "staging_tables", _mig_v3_staging_tables,
    rollback_sql="DROP TABLE IF EXISTS field_conflicts, contact_merges, contact_emails, "
                 "email_staged_links, staged_contacts; ALTER TABLE companies DROP COLUMN website_key"))
_register(_Migration(4, "backfill_staged_from_eml", _mig_v4_backfill_staged,
    rollback_sql="DELETE FROM staged_contacts WHERE source_type='eml'"))
_register(_Migration(5, "backfill_links_and_status", _mig_v5_backfill_links_status,
    rollback_sql="DELETE FROM email_staged_links WHERE staged_contact_id IN "
                 "(SELECT id FROM staged_contacts WHERE source_type='eml'); "
                 "UPDATE staged_contacts SET validation_warnings=NULL WHERE source_type='eml'"))
_register(_Migration(6, "rebuild_contacts_fk_keys", _mig_v6_rebuild_contacts,
    rollback_sql="-- structural rebuild: roll back with db.restore_database(step-0 backup)",
    fk_off=True))
_register(_Migration(9, "verify_and_log", _mig_v9_verify_and_log, rollback_sql=None))
_register(_Migration(10, "drop_records_if_empty", _mig_v10_drop_records,
    rollback_sql="-- table was empty when dropped; recreate from the legacy DDL if ever needed"))

def run_migrations(con: sqlite3.Connection, target: int = CURRENT_MIGRATION_VERSION,
                   force: bool = False) -> list[int]:
    """Apply pending versioned migrations in order; returns the versions applied.

    Each migration runs in its own explicit transaction and is logged to
    _migration_log with rollback_sql + checksum; a failure rolls back only that
    migration (rerun resumes). Calls are idempotent (IF NOT EXISTS / guards).

    D-030 gate: the canonical live DB is migrated ONLY by the explicit gated
    step — set CRM_APPLY_MIGRATIONS=1 or pass force=True. App startups, tests
    and CI must never restructure production data by accident. Exception: a
    database with zero user rows (fresh install) carries no data to protect,
    so the additive train self-provisions there; the gate applies as soon as
    any contacts/emails/processed_files exist.
    """
    con_file = _con_db_file(con)
    if not force and os.environ.get(_MIGRATION_GATE_ENV) != "1" and con_file == _live_db_file():
        try:
            user_rows = con.execute(
                "SELECT (SELECT count(*) FROM contacts) + (SELECT count(*) FROM eml_emails)"
                " + (SELECT count(*) FROM eml_contacts) + (SELECT count(*) FROM processed_files)"
            ).fetchone()[0]
        except sqlite3.Error:
            user_rows = 0
        if user_rows > 0:
            try:
                have = {r[0] for r in con.execute("SELECT version FROM _migration_log")}
            except sqlite3.Error:
                have = set()
            pend = [v for v in sorted(_MIGRATIONS) if v not in have and v <= target]
            if pend:
                sys.stderr.write(
                    f"[db] D-030 gate: migrations {pend} pending on live DB ({con_file}); "
                    f"apply with {_MIGRATION_GATE_ENV}=1 after the step-0 backup\n")
            return []

    con.execute(
        "CREATE TABLE IF NOT EXISTS _migration_log ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL,"
        " rollback_sql TEXT, checksum TEXT)"
    )
    applied = {r[0] for r in con.execute("SELECT version FROM _migration_log")}
    pending = [_MIGRATIONS[v] for v in sorted(_MIGRATIONS)
               if v not in applied and v <= target]
    applied_now: list[int] = []
    con.commit()  # close any caller-open implicit txn before autocommit mode
    old_iso = con.isolation_level
    con.isolation_level = None  # explicit BEGIN/COMMIT; executescript is forbidden here
    try:
        for m in pending:
            if m.fk_off:
                con.execute("PRAGMA foreign_keys=OFF")  # must precede BEGIN
            con.execute("BEGIN")
            try:
                m.fn(con)
                con.execute(
                    "INSERT OR REPLACE INTO _migration_log"
                    " (version, name, applied_at, rollback_sql, checksum)"
                    " VALUES (?, ?, datetime('now'), ?, ?)",
                    (m.version, m.name, m.rollback_sql, m.checksum()),
                )
                con.execute("COMMIT")
            except Exception as e:
                try:
                    con.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise MigrationError(f"migration v{m.version} ({m.name}) failed: {e}") from e
            finally:
                if m.fk_off:
                    con.execute("PRAGMA foreign_keys=ON")
            applied_now.append(m.version)
        if applied_now:
            # post-train gates (v9's PRAGMA half) — run after the LAST migration
            bad = con.execute("PRAGMA integrity_check").fetchone()[0]
            if bad != "ok":
                raise MigrationError(f"integrity_check failed after migration: {bad}")
            fk_rows = con.execute("PRAGMA foreign_key_check").fetchall()
            if fk_rows:
                raise MigrationError(f"foreign_key_check failed: {fk_rows[:5]}")
    finally:
        con.isolation_level = old_iso
    return applied_now

def backup_database(dest, src=None) -> str:
    """Consistent hot backup via sqlite3's backup API (WAL-safe) — D-030 step 0.
    Verifies the copy with PRAGMA integrity_check; returns the dest path."""
    src_path = str(src or config.db_path("crm"))
    dest_path = str(dest)
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    src_con = sqlite3.connect(src_path, timeout=30)
    try:
        dst_con = sqlite3.connect(dest_path)
        try:
            src_con.backup(dst_con)
        finally:
            dst_con.close()
    finally:
        src_con.close()
    chk = sqlite3.connect(dest_path)
    try:
        bad = chk.execute("PRAGMA integrity_check").fetchone()[0]
        if bad != "ok":
            raise MigrationError(f"backup failed integrity_check: {bad}")
    finally:
        chk.close()
    return dest_path

def restore_database(backup, dest=None) -> str:
    """Atomically replace dest with the backup (WAL/SHM sidecars removed first).
    Run while the app is stopped: connections opened earlier keep the old file."""
    dest_path = str(dest or config.db_path("crm"))
    backup_path = str(backup)
    if not os.path.exists(backup_path):
        raise MigrationError(f"backup not found: {backup_path}")
    chk = sqlite3.connect(backup_path)
    try:
        bad = chk.execute("PRAGMA integrity_check").fetchone()[0]
        if bad != "ok":
            raise MigrationError(f"backup corrupt: {bad}")
    finally:
        chk.close()
    tmp_path = dest_path + ".restore-tmp"
    Path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(backup_path, tmp_path)
    for sidecar in (dest_path + "-wal", dest_path + "-shm"):
        if os.path.exists(sidecar):
            os.remove(sidecar)
    os.replace(tmp_path, dest_path)
    return dest_path

def insert_email(con, parsed, file_path):
    cur = con.execute("""
        INSERT INTO eml_emails (file_name, file_path, subject, date, sender_name, sender_email,
            receiver_name, receiver_email,
            to_emails, cc_emails, bcc_emails, body_text, has_signature, processed_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        os.path.basename(file_path), file_path, getattr(parsed, "subject", None),
        getattr(parsed, "date", None), getattr(parsed, "sender_name", None),
        getattr(parsed, "sender_email", None),
        getattr(parsed, "receiver_name", None), getattr(parsed, "receiver_email", None),
        getattr(parsed, "to_emails", None),
        getattr(parsed, "cc_emails", None), getattr(parsed, "bcc_emails", None),
        getattr(parsed, "body_text", None), int(getattr(parsed, "has_signature", False)),
        now_iso(), now_iso(),
    ))
    return cur.lastrowid

def _table_cols(con, table: str) -> set[str]:
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.Error:
        return set()

def counts():
    """DB counters for /api/status. Additive keys; missing tables (pre-migration
    live DB) or missing columns (deleted_at before v6) degrade to 0, never raise."""
    con = connect("crm")
    try:
        contact_cols = _table_cols(con, "contacts")
        live = "deleted_at IS NULL" if "deleted_at" in contact_cols else "1=1"
        c = con.execute(f"SELECT count(*) FROM contacts WHERE {live}").fetchone()[0]
        e = con.execute("SELECT count(*) FROM eml_contacts").fetchone()[0]
        em = con.execute("SELECT count(*) FROM eml_emails").fetchone()[0]
        pf = con.execute("SELECT count(*) FROM processed_files").fetchone()[0]
        out = {"crm": c, "eml": e, "eml_contacts": e, "emails": em,
               "processed_files": pf}

        # staged pending review (needs the v3 table; absent pre-migration)
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='staged_contacts'").fetchone():
            out["staged"] = con.execute(
                "SELECT count(*) FROM staged_contacts"
                " WHERE review_status IN ('NEW','NEEDS_REVIEW','READY')").fetchone()[0]
        else:
            out["staged"] = 0

        # "new" = contacts created in the last 30 days (ISO strings compare lexicographically)
        cutoff = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
        out["new"] = con.execute(
            f"SELECT count(*) FROM contacts WHERE {live} AND created_at >= ?", (cutoff,)).fetchone()[0]

        # duplicates: contacts (live) sharing a normalized email_key or phone_key
        dup_sql = f"""SELECT count(*) FROM contacts WHERE {live} AND (
            email_key IN (SELECT email_key FROM contacts WHERE email_key IS NOT NULL AND {live}
                          GROUP BY email_key HAVING count(*) > 1) OR
            phone_key IN (SELECT phone_key FROM contacts WHERE phone_key IS NOT NULL AND {live}
                          GROUP BY phone_key HAVING count(*) > 1))"""
        out["duplicates"] = con.execute(dup_sql).fetchone()[0]

        # field-quality counters over live contacts — same rules the server enforces
        from services import validation as _validation
        rows = con.execute(
            f"SELECT name, email_primary, email_secondary, phone_primary, phone_secondary,"
            f" whatsapp, pincode, company, position, designation, address, city, website"
            f" FROM contacts WHERE {live}").fetchall()
        inv_emails = sum(1 for r in rows
                         if _validation.validate_email(r["email_primary"], "email_primary")
                         or _validation.validate_email(r["email_secondary"], "email_secondary"))
        inv_phones = sum(1 for r in rows
                         if _validation.validate_phone(r["phone_primary"], "phone_primary")
                         or _validation.validate_phone(r["phone_secondary"], "phone_secondary")
                         or _validation.validate_phone(r["whatsapp"], "whatsapp"))
        incomplete = sum(1 for r in rows
                         if not (r["name"] and str(r["name"]).strip())
                         or not ((r["email_primary"] and str(r["email_primary"]).strip())
                                 or (r["phone_primary"] and str(r["phone_primary"]).strip())))
        out["invalid_emails"] = inv_emails
        out["invalid_phones"] = inv_phones
        out["incomplete_records"] = incomplete
        return out
    finally:
        con.close()

def is_processed(con, path, size, mtime):
    r = con.execute("SELECT 1 FROM processed_files WHERE path=? AND size=? AND mtime=?",
                    (path, size, mtime)).fetchone()
    return r is not None

def mark_processed(con, path, size, mtime, status, detail=None, contacts_found=0):
    con.execute("""
        INSERT INTO processed_files (path, size, mtime, status, detail, contacts_found, processed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime,
            status=excluded.status, detail=excluded.detail,
            contacts_found=excluded.contacts_found, processed_at=excluded.processed_at
    """, (path, size, mtime, status, detail, contacts_found, now_iso()))