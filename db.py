# db.py — two independent SQLite stores: crm.db and eml.db.
import re
import sqlite3
from datetime import datetime, timezone

import config

CONTACT_FIELDS = [
    "name", "email_primary", "email_secondary", "phone_primary", "phone_secondary",
    "company", "designation", "address", "city", "pincode", "website",
]

_CONTACT_COLS = (
    "name, email_primary, email_secondary, phone_primary, phone_secondary, "
    "company, designation, address, city, pincode, website, email_key, phone_key, "
    "source_file, created_at, updated_at"
)

_SCHEMA_CRM = """
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT, email_primary TEXT, email_secondary TEXT,
  phone_primary TEXT, phone_secondary TEXT,
  company TEXT, designation TEXT, address TEXT, city TEXT, pincode TEXT, website TEXT,
  email_key TEXT, phone_key TEXT,
  source_file TEXT, created_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_contacts_email_key ON contacts(email_key);
CREATE INDEX IF NOT EXISTS idx_contacts_phone_key ON contacts(phone_key);
CREATE TABLE IF NOT EXISTS processed_files (
  path TEXT PRIMARY KEY, size INTEGER, mtime REAL, status TEXT, detail TEXT,
  contacts_found INTEGER DEFAULT 0, processed_at TEXT
);
"""

_SCHEMA_EML = """
CREATE TABLE IF NOT EXISTS eml_contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email_id INTEGER,
  name TEXT, email_primary TEXT, email_secondary TEXT,
  phone_primary TEXT, phone_secondary TEXT,
  company TEXT, designation TEXT, address TEXT, city TEXT, pincode TEXT, website TEXT,
  email_key TEXT, phone_key TEXT,
  source_file TEXT, status TEXT, pushed INTEGER DEFAULT 0,
  created_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_eml_contacts_email_key ON eml_contacts(email_key);
CREATE INDEX IF NOT EXISTS idx_eml_contacts_phone_key ON eml_contacts(phone_key);
CREATE TABLE IF NOT EXISTS emails (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_name TEXT, file_path TEXT, subject TEXT, date TEXT,
  sender_name TEXT, sender_email TEXT,
  to_emails TEXT, cc_emails TEXT, bcc_emails TEXT,
  body_text TEXT, has_signature INTEGER, processed_at TEXT
);
CREATE TABLE IF NOT EXISTS processed_files (
  path TEXT PRIMARY KEY, size INTEGER, mtime REAL, status TEXT, detail TEXT,
  contacts_found INTEGER DEFAULT 0, processed_at TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(which: str) -> sqlite3.Connection:
    con = sqlite3.connect(config.db_path(which), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init() -> None:
    for which, schema in (("crm", _SCHEMA_CRM), ("eml", _SCHEMA_EML)):
        con = connect(which)
        con.executescript(schema)
        con.commit()
        con.close()


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def phone_key(phone: str | None) -> str:
    """Digits only, with Indian country-code / trunk-prefix variance removed.
    shortcut: only 91/+91 and leading-0 variance is collapsed; upgrade if other
    country codes need matching."""
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 12 and d.startswith("91"):
        return d[2:]
    if len(d) == 11 and d.startswith("0"):
        return d[1:]
    return d


class DedupIndex:
    """In-memory email/phone/name sets loaded once per scan."""

    def __init__(self):
        self.emails: set[str] = set()
        self.phones: set[str] = set()
        self.names: set[str] = set()

    @classmethod
    def load(cls, con: sqlite3.Connection, table: str, with_names: bool = False) -> "DedupIndex":
        idx = cls()
        for row in con.execute(f"SELECT email_key, phone_key, name FROM {table}"):
            if row["email_key"]:
                idx.emails.add(row["email_key"])
            if row["phone_key"]:
                idx.phones.add(row["phone_key"])
            if with_names and row["name"]:
                idx.names.add(row["name"].strip().lower())
        return idx

    def add(self, email: str | None, phone: str | None, name: str | None) -> None:
        e = normalize_email(email)
        p = phone_key(phone)
        if e:
            self.emails.add(e)
        if p:
            self.phones.add(p)
        if name:
            self.names.add(name.strip().lower())

    def duplicate_reason(self, email: str | None, phone: str | None, name: str | None = None) -> str | None:
        e = normalize_email(email)
        if e and e in self.emails:
            return "email"
        p = phone_key(phone)
        if len(p) >= 10 and p in self.phones:
            return "phone"
        if name:
            n = name.strip().lower()
            if len(n) >= 3 and n in self.names:
                return "name"
        return None


def _find(con: sqlite3.Connection, table: str, email: str | None, phone: str | None,
          name: str | None, use_name: bool) -> sqlite3.Row | None:
    e = normalize_email(email)
    p = phone_key(phone)
    if e:
        row = con.execute(f"SELECT * FROM {table} WHERE email_key=?", (e,)).fetchone()
        if row:
            return row
    if len(p) >= 10:
        row = con.execute(f"SELECT * FROM {table} WHERE phone_key=?", (p,)).fetchone()
        if row:
            return row
    if use_name and name and len(name.strip()) >= 3:
        return con.execute(
            f"SELECT * FROM {table} WHERE lower(trim(name))=?", (name.strip().lower(),)
        ).fetchone()
    return None


def upsert_contact(con: sqlite3.Connection, fields: dict, table: str = "contacts",
                   source_file: str = "", use_name: bool = False) -> tuple[int, str]:
    """Merge-or-create. Existing rows are only enriched, never overwritten.
    Returns (id, 'new'|'merged')."""
    row = _find(con, table, fields.get("email_primary"), fields.get("phone_primary"),
                fields.get("name"), use_name)
    now = now_iso()
    if row:
        updates: dict[str, object] = {}
        for f in CONTACT_FIELDS:
            v = fields.get(f)
            if v and not row[f]:
                updates[f] = v
        # Backfill dedup keys when the existing row had none.
        e = normalize_email(fields.get("email_primary"))
        p = phone_key(fields.get("phone_primary"))
        if e and not row["email_key"]:
            updates["email_key"] = e
        if p and not row["phone_key"]:
            updates["phone_key"] = p
        if updates:
            updates["updated_at"] = now
            sets = ", ".join(f"{k}=?" for k in updates)
            con.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*updates.values(), row["id"]))
        return row["id"], "merged"

    vals = [fields.get(f) for f in CONTACT_FIELDS]
    vals += [normalize_email(fields.get("email_primary")),
             phone_key(fields.get("phone_primary")),
             source_file, now, now]
    con.execute(f"INSERT INTO {table} ({_CONTACT_COLS}) VALUES ({','.join('?' * len(vals))})", vals)
    return con.execute("SELECT last_insert_rowid()").fetchone()[0], "new"


def insert_email(con: sqlite3.Connection, parsed, file_path: str) -> int:
    con.execute(
        "INSERT INTO emails (file_name, file_path, subject, date, sender_name, sender_email, "
        "to_emails, cc_emails, bcc_emails, body_text, has_signature, processed_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (parsed.file_name, file_path, parsed.subject, parsed.date, parsed.sender_name,
         parsed.sender_email, parsed.to_emails, parsed.cc_emails, parsed.bcc_emails,
         parsed.body_text, int(parsed.has_signature), now_iso()),
    )
    return con.execute("SELECT last_insert_rowid()").fetchone()[0]


def insert_eml_contact(con: sqlite3.Connection, email_id: int, fields: dict,
                       status: str, source_file: str = "") -> int:
    now = now_iso()
    vals = [email_id] + [fields.get(f) for f in CONTACT_FIELDS]
    vals += [normalize_email(fields.get("email_primary")),
             phone_key(fields.get("phone_primary")),
             source_file, status, 0, now, now]
    con.execute(
        "INSERT INTO eml_contacts (email_id, " + _CONTACT_COLS + ", status, pushed) "
        "VALUES (" + ",".join("?" * len(vals)) + ")",
        vals,
    )
    return con.execute("SELECT last_insert_rowid()").fetchone()[0]


def mark_pushed(con: sqlite3.Connection, contact_id: int) -> None:
    con.execute("UPDATE eml_contacts SET pushed=1 WHERE id=?", (contact_id,))


def list_contacts(con: sqlite3.Connection, table: str, q: str = "", page: int = 1,
                  size: int = 50) -> tuple[list[dict], int]:
    page = max(1, int(page))
    size = min(200, max(1, int(size)))
    where, args = "", []
    if q:
        where = (" WHERE name LIKE ? OR email_primary LIKE ? OR email_secondary LIKE ? "
                 "OR phone_primary LIKE ? OR phone_secondary LIKE ? OR company LIKE ?")
        args = [f"%{q}%"] * 6
    total = con.execute(f"SELECT count(*) FROM {table}{where}", args).fetchone()[0]
    rows = con.execute(
        f"SELECT * FROM {table}{where} ORDER BY id DESC LIMIT ? OFFSET ?",
        (*args, size, (page - 1) * size),
    ).fetchall()
    return [dict(r) for r in rows], total


def get_contact(con: sqlite3.Connection, table: str, contact_id: int) -> dict | None:
    row = con.execute(f"SELECT * FROM {table} WHERE id=?", (contact_id,)).fetchone()
    return dict(row) if row else None


def update_contact(con: sqlite3.Connection, table: str, contact_id: int, fields: dict) -> bool:
    updates = {f: fields.get(f) for f in CONTACT_FIELDS if f in fields}
    if not updates:
        return False
    updates["email_key"] = normalize_email(fields.get("email_primary"))
    updates["phone_key"] = phone_key(fields.get("phone_primary"))
    updates["updated_at"] = now_iso()
    sets = ", ".join(f"{k}=?" for k in updates)
    cur = con.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*updates.values(), contact_id))
    return cur.rowcount > 0


def delete_contact(con: sqlite3.Connection, table: str, contact_id: int) -> bool:
    cur = con.execute(f"DELETE FROM {table} WHERE id=?", (contact_id,))
    return cur.rowcount > 0


def counts() -> dict:
    out = {"crm": 0, "eml": 0, "eml_emails": 0}
    crm = connect("crm")
    out["crm"] = crm.execute("SELECT count(*) FROM contacts").fetchone()[0]
    crm.close()
    eml = connect("eml")
    out["eml"] = eml.execute("SELECT count(*) FROM eml_contacts").fetchone()[0]
    out["eml_emails"] = eml.execute("SELECT count(*) FROM emails").fetchone()[0]
    eml.close()
    return out


def is_processed(con: sqlite3.Connection, path: str, size: int, mtime: float) -> bool:
    row = con.execute("SELECT size, mtime FROM processed_files WHERE path=?", (path,)).fetchone()
    return bool(row) and row["size"] == size and abs(row["mtime"] - mtime) < 1e-6


def mark_processed(con: sqlite3.Connection, path: str, size: int, mtime: float,
                   status: str, detail: str = "", contacts_found: int = 0) -> None:
    con.execute(
        "INSERT INTO processed_files (path, size, mtime, status, detail, contacts_found, processed_at) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET "
        "size=excluded.size, mtime=excluded.mtime, status=excluded.status, "
        "detail=excluded.detail, contacts_found=excluded.contacts_found, "
        "processed_at=excluded.processed_at",
        (path, size, mtime, status, detail, contacts_found, now_iso()),
    )
