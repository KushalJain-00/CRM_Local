# db.py — Unified SQLite store for CRM_Local (single database, all tables).
import re
import sqlite3
import os
import shutil
from datetime import datetime, timezone

import config

# Unified database: single file for all CRM + EML data (D-014)
_UNIFIED_DB = "crm.db"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(which: str = "crm") -> sqlite3.Connection:
    """Connect to the unified database. 'which' param kept for backward compat."""
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

CREATE TABLE IF NOT EXISTS records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER REFERENCES session_data(id) ON DELETE CASCADE,
  data TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_session_id ON records(session_id);

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
                    r["email_key"], r["phone_key"], r["created_at"], r["updated_at"],
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


# Backward-compatible aliases
connect_crm = lambda: connect("crm")
connect_eml = lambda: connect("crm")  # Both connect to unified DB now

# Preserve old function names for backward compat
def connect(which: str = "crm") -> sqlite3.Connection:
    con = sqlite3.connect(config.db_path("crm"), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


# Phone normalization (shared, G14)
def phone_key(phone: str | None) -> str | None:
    """Digits only, with Indian country-code / trunk-prefix variance removed."""
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    if len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return d if len(d) >= 7 else None


# Keep original functions that other modules depend on
# (upsert_contact, insert_email, insert_eml_contact, mark_pushed, list_contacts, etc.)
# These are in the original db.py — import them from here for backward compat

# Re-export from original module structure
import sqlite3 as _sqlite3

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

# The following functions are preserved from the original db.py:
# normalize_email, phone_key (above), DedupIndex, upsert_contact, insert_email,
# insert_eml_contact, mark_pushed, list_contacts, get_contact, update_contact,
# delete_contact, counts, is_processed, mark_processed

# For backward compat, provide connect(which) that ignores 'which' param
def connect(which: str = "crm") -> sqlite3.Connection:
    con = sqlite3.connect(config.db_path("crm"), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


# Import original helper functions by exec'ing the old db.py logic
# (We'll keep them inline for simplicity)

def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


class DedupIndex:
    def __init__(self):
        self.emails: set[str] = set()
        self.phones: set[str] = set()
        self.names: set[str] = set()

    @classmethod
    def load(cls, con: sqlite3.Connection, table: str, with_names: bool = False) -> "DedupIndex":
        idx = cls()
        try:
            rows = con.execute(f"SELECT email_primary, phone_primary, name FROM {table}").fetchall()
        except Exception:
            try:
                rows = con.execute(f"SELECT email, phone_primary, name FROM {table}").fetchall()
            except Exception:
                return idx
        for r in rows:
            idx.add(r["email_primary"] if "email_primary" in r.keys() else r["email"],
                    r["phone_primary"], r["name"] if with_names else None)
        return idx

    def add(self, email, phone, name=None):
        if email:
            self.emails.add(normalize_email(email))
        pk = phone_key(phone)
        if pk:
            self.phones.add(pk)
        if name:
            self.names.add(" ".join((name or "").split()).lower())

    def duplicate_reason(self, email, phone, name=None):
        e = normalize_email(email)
        if e and e in self.emails:
            return "email"
        pk = phone_key(phone)
        if pk and len(pk) >= 10:
            for ep in self.phones:
                if ep == pk or (len(ep) >= 10 and (ep in pk or pk in ep)):
                    return "phone"
        if name:
            n = " ".join((name or "").split()).lower()
            if n and len(n) >= 3 and n in self.names:
                return "name"
        return None


def _find(con, table, email, phone, name=None):
    # Find existing contact by email, phone, or name+phone
    if email:
        r = con.execute(f"SELECT * FROM {table} WHERE email_primary = ?", (email,)).fetchone()
        if r:
            return dict(r)
    if phone:
        pk = phone_key(phone)
        r = con.execute(f"SELECT * FROM {table} WHERE phone_primary = ?", (phone,)).fetchone()
        if r:
            return dict(r)
    if name and phone:
        r = con.execute(f"SELECT * FROM {table} WHERE name = ? AND phone_primary = ?", (name, phone)).fetchone()
        if r:
            return dict(r)
    return None


def upsert_contact(con, fields, table="contacts", source_file=None):
    """Merge-or-create a contact. Returns (id, 'new'|'merged'|'skipped')."""
    email = (fields.get("email_primary") or fields.get("email") or "").strip().lower()
    phone = (fields.get("phone_primary") or fields.get("phone") or "").strip()
    name = (fields.get("name") or "").strip()

    existing = _find(con, table, email, phone, name)
    if existing:
        # Enrich empty fields only
        merged = False
        for key in ["name", "email_primary", "phone_primary", "company", "designation",
                    "address", "city", "pincode", "website", "email_secondary", "phone_secondary"]:
            val = fields.get(key)
            if val and not existing.get(key):
                con.execute(f"UPDATE {table} SET {key} = ? WHERE id = ?", (val, existing["id"]))
                merged = True
        # Update dedup keys
        if email:
            con.execute(f"UPDATE {table} SET email_key = ? WHERE id = ?", (email, existing["id"]))
        if phone:
            con.execute(f"UPDATE {table} SET phone_key = ? WHERE id = ?", (phone_key(phone), existing["id"]))
        if source_file:
            con.execute(f"UPDATE {table} SET source_file = ? WHERE id = ? AND source_file IS NULL", (source_file, existing["id"]))
        return existing["id"], ("merged" if merged else "skipped")
    else:
        cols = "name, email_primary, email_secondary, phone_primary, phone_secondary, company, designation, address, city, pincode, website, email_key, phone_key, source_file, created_at, updated_at"
        vals = (name or None, email or None, fields.get("email_secondary"), phone or None,
                fields.get("phone_secondary"), fields.get("company"), fields.get("designation"),
                fields.get("address"), fields.get("city"), fields.get("pincode"), fields.get("website"),
                email or None, phone_key(phone), source_file, now_iso(), now_iso())
        cur = con.execute(f"INSERT INTO {table} ({cols}) VALUES ({','.join('?'*16)})", vals)
        return cur.lastrowid, "new"


def insert_email(con, parsed, file_path):
    cur = con.execute("""
        INSERT INTO eml_emails (file_name, file_path, subject, date, sender_name, sender_email,
            to_emails, cc_emails, bcc_emails, body_text, has_signature, processed_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        os.path.basename(file_path), file_path, getattr(parsed, "subject", None),
        getattr(parsed, "date", None), getattr(parsed, "sender_name", None),
        getattr(parsed, "sender_email", None), getattr(parsed, "to_emails", None),
        getattr(parsed, "cc_emails", None), getattr(parsed, "bcc_emails", None),
        getattr(parsed, "body_text", None), int(getattr(parsed, "has_signature", False)),
        now_iso(), now_iso(),
    ))
    return cur.lastrowid


def insert_eml_contact(con, email_id, fields, status="NEW", source_file=""):
    cur = con.execute("""
        INSERT INTO eml_contacts (source_email_id, name, email, phone_primary, phone_secondary,
            company, designation, address, city, pincode, website, dedup_status, pushed_to_crm,
            source_file, email_key, phone_key, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
    """, (
        email_id, fields.get("name"), fields.get("email_primary") or fields.get("email"),
        fields.get("phone_primary"), fields.get("phone_secondary"), fields.get("company"),
        fields.get("designation"), fields.get("address"), fields.get("city"),
        fields.get("pincode"), fields.get("website"), status, source_file or fields.get("source_file"),
        normalize_email(fields.get("email_primary") or fields.get("email")),
        phone_key(fields.get("phone_primary")), now_iso(), now_iso(),
    ))
    return cur.lastrowid


def mark_pushed(con, contact_id):
    con.execute("UPDATE eml_contacts SET pushed_to_crm = 1 WHERE id = ?", (contact_id,))


def list_contacts(con, table, q="", page=1, size=50):
    offset = (page - 1) * size
    if q:
        like = f"%{q}%"
        rows = con.execute(f"""
            SELECT * FROM {table} WHERE name LIKE ? OR email_primary LIKE ? OR phone_primary LIKE ? OR company LIKE ?
            ORDER BY id DESC LIMIT ? OFFSET ?
        """, (like, like, like, like, size, offset)).fetchall()
        total = con.execute(f"""
            SELECT count(*) FROM {table} WHERE name LIKE ? OR email_primary LIKE ? OR phone_primary LIKE ? OR company LIKE ?
        """, (like, like, like, like)).fetchone()[0]
    else:
        rows = con.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ? OFFSET ?", (size, offset)).fetchall()
        total = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    return [dict(r) for r in rows], total


def get_contact(con, table, contact_id):
    r = con.execute(f"SELECT * FROM {table} WHERE id = ?", (contact_id,)).fetchone()
    return dict(r) if r else None


def update_contact(con, table, contact_id, fields):
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [contact_id]
    con.execute(f"UPDATE {table} SET {sets} WHERE id = ?", vals)
    return con.total_changes > 0


def delete_contact(con, table, contact_id):
    con.execute(f"DELETE FROM {table} WHERE id = ?", (contact_id,))
    return con.total_changes > 0


def counts():
    con = connect("crm")
    c = con.execute("SELECT count(*) FROM contacts").fetchone()[0]
    e = con.execute("SELECT count(*) FROM eml_contacts").fetchone()[0]
    em = con.execute("SELECT count(*) FROM eml_emails").fetchone()[0]
    con.close()
    return {"crm": c, "eml": e, "eml_contacts": e, "emails": em}


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