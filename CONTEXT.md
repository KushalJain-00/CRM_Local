# Context — CRM Local

This file provides the domain, technical, and operational context for the CRM Local project. It is intended to be a stable reference that survives across sessions and is safe for AI agents to read and reference.

## Master Brief (2026-11-07)

The project originated from a master brief session. Key constraints and mandates:

- **Local-first, offline-capable**: No cloud services, no mandatory authentication, no remote frontend dependencies, no mandatory paid APIs. Fully useful offline; external services are explicit opt-ins.
- **One of everything**: One app, one database, one intake, one extraction engine, one staging system, one CRM workspace.
- **Six source formats** through one intake → one extraction engine → one unified staging system → canonical CRM (contacts, companies, emails, call logs).
- **Two-layer extraction**: Layer 1 deterministic local (always, offline); Layer 2 optional AI enrichment that fills gaps only — never overwrites populated local values, never invents, carries per-field evidence with confidence labels.
- **Staging has three independent status dimensions**: review (NEW/NEEDS_REVIEW/READY/APPROVED/REJECTED/DISMISSED), dedup (NOT_CHECKED/UNIQUE/EXACT_DUPLICATE/PROBABLE_DUPLICATE/CONFLICT), import (NOT_IMPORTED/NEW_CONTACT_CREATED/EXISTING_CONTACT_ENRICHED/IMPORT_FAILED). Import policies: Review First / Smart Import / Always Stage, user-selectable.
- **CRM workspace**: Dashboard, Import Center, Review Queue, Contacts (10,000+ records, server-side pagination), Companies (with merge), Emails (two-pane browser), Calls & Activities, Duplicates, Data Quality, Processing History, Reports & Exports (XLSX/CSV/PDF/VCF/ZIP, formula-injection protection), Settings (7 providers, secrets never exposed to browser JS), Help.
- **Hard constraints**: exactly one SQLite database; no Supabase/cloud auth/telemetry; no CDN or remote frontend dependencies; bundled local fonts/assets; **no graphs or charts anywhere**; vanilla JS with native ES modules (no new framework); PyInstaller compatibility; WCAG 2.2 AA; prompt-injection resistance; export formula protection.
- **Product principles**:
  1. Never invent information — every extracted value carries source evidence; humans approve before it becomes canonical.
  2. One of everything — one app, one database, one intake, one extraction engine, one staging system, one provider manager.
  3. Local-first — fully useful offline; external services are explicit opt-ins.
  4. Preserve source truth — raw records, original emails, and provenance are never discarded; enrichment never silently overwrites populated fields (local-wins).
  5. Dense, calm, content-first professional tool — precision over decoration; no charts.

## Domain Model

### Six Source Formats

| Format | Extension | Adapter | Extraction Method |
|---|---|---|---|
| Spreadsheet | `.xlsx`, `.xls` | `services/adapters/xlsx.py`, `services/adapters/xls.py` (via `parser.py`) | Header mapping by meaning; regex for XLS; openpyxl for XLSX |
| PDF | `.pdf` | `services/adapters/pdf.py` (via `parser.py`) | pdfplumber (MIT) table extraction; labeled-line fallback paired per record |
| CSV | `.csv` | `services/adapters/csv.py` | Header-by-meaning mapping; `utf-8-sig` encoding |
| TXT | `.txt` | `services/adapters/txt.py` | Regex phone extraction; contact-shaped structures only |
| EML | `.eml` | `services/adapters/eml.py` (via `eml_processor.py`) | Python `email` module MIME parsing; signature detection; local field extraction |
| Universal intake | All formats | `services/intake.py` | Multipart upload; server receives bytes, never filesystem paths |

### Contact Fields (extracted + stored)

**Primary identity**: `name`, `email_primary`, `phone_primary`
**Secondary**: `email_secondary`, `phone_secondary`, `whatsapp`
**Company**: `company`, `designation`/`position`, `address`, `city`, `pincode`, `website`
**Evidence**: `field_evidence` (object with `excerpt`, `location`, `confidence` per field), `confidence` (`high`/`medium`/`low`)
**Provenance**: `source_file`, `source_row`, `source_file_id`, `extraction_run_id`, `field_origin`

### Company Fields

`name`, `address`, `city`, `pincode`, `website`, `industry`, `product`
CHECK constraints enforce valid company name format (no role titles without company suffix).

### Three Status Dimensions (staged_contacts)

| Dimension | Values |
|---|---|
| **review_status** | NEW → NEEDS_REVIEW → READY/APPROVED/REJECTED/DISMISSED |
| **dedup_status** | NOT_CHECKED → UNIQUE/EXACT_DUPLICATE/PROBABLE_DUPLICATE/CONFLICT |
| **import_status** | NOT_IMPORTED → NEW_CONTACT_CREATED/EXISTING_CONTACT_ENRICHED/IMPORT_FAILED |

### Contact Dedup Keys (spec §6.5)

- `name_key` = `lower(collapse_ws(v))` — honorifics stripped, collapsed whitespace, dots/commas/quotes/parens removed
- `company_key` = `lower(tokens - legal_tokens)` — legal tokens (pvt, ltd, limited, llp, inc, corp, co, company, gmbh, plc, srl, pte, the) removed from company name tokens
- `website_key` = `host, lower, no scheme/'www'/path, stripped trailing dots` — e.g., `example.com`
- `email_key` = `normalize_email(value)` — strip, lowercase

### Migration Train (D-030 Dated D-030 | 2026-11-07)

Migrations v1→v10 applied in order, gated by `CRM_APPLY_MIGRATIONS=1`.

- **v1**: Unified schema + column ensure + eml data migration — baseline
- **v2**: `eml_emails.receiver_name`/`receiver_email` columns + backfill
- **v3**: `staged_contacts` + relationship/tables + CHECK enums + `companies.website_key`
- **v4**: Backfill `staged_contacts` from `eml_contacts` (all 17 fields; `raw_source_data` = JSON of old row)
- **v5**: `email_staged_links` (source_email_id, EXISTS-guarded) + D-015 phantom row warnings
- **v6**: Rebuild `contacts` table (real FKs to `companies` + `extraction_runs`; dedup keys; `deleted_at` soft-delete; `position` backfilled from `designation`)
- **v7**: `eml_contacts` → VIEW (deferred to Phase 2; must ship same release as write-path redirection)
- **v8**: FTS5 (deferred to Phase 5; global search)
- **v9**: Structural verification (PRAGMA integrity_check + foreign_key_check; staged eml count = eml_contacts count; no dangling links; no phantom rows without D-015 warning; no views; no FTS5)
- **v10**: Drop empty `records` table (zero readers, zero writers in repo)

**Phase 1 (shipped)** additive subset: v5c (status backfills + warnings), v6 (contacts rebuild FK + dedup keys + backup + count verification), v7 (staged_contacts + relationship tables + CHECK enums + receiver_name/receiver_email), v7 write-path redirection.

**Phase 2**: `eml_contacts` → VIEW, FTS5, default import policy decision.

### Security Model (D-028 / SEC-01 through SEC-10)

- **SEC-01**: `api_key` masked on ALL four config/settings endpoints (GET/POST `/api/config`, GET/POST `/api/settings`) + `app.py:106-112,125,160-172` responses
- **SEC-02**: Server-side sanitizer stopgap for `innerHTML` sinks (Phase 6 CSP)
- **SEC-03**: Origin/Host validation middleware for loopback (blocks cross-site simple POSTs + DNS-rebinding key reads)
- **SEC-04**: Provider chain never echoes raw keys in any response
- **SEC-05**: Server receives bytes, never filesystem paths (universal intake D-009)
- **SEC-06**: Prompt content capped and delimited (MAX_CONTENT_CHARS=8000, UNTRUSTED markers)
- **SEC-07**: EML header byte caps (subject ≤200, headers ≤100, key ≤40) — mirrored byte-for-byte to CRM_Developer
- **SEC-08**: LLM never emits DB-owned fields (id, timestamps, crm_contact_id, etc.) via BANNED_DB_KEYS check
- **SEC-09**: `config.json` forced to 0600 at startup via `config.lock_down()` + `_private()` chmod
- **SEC-10**: Header caps in `services/eml_processor.py` mirrored to `CRM_Developer` (byte-identical shared file)

### Extractor Contract (crm-extraction.v1)

Single shared JSON contract embedded in every extraction request. Validated by `services/contract.py validate_extraction_result()`. Schema:

```json
{
  "schema_version": "crm-extraction.v1",
  "source_type": "spreadsheet|pdf|csv|txt|eml",
  "companies": [{"name": None, "address": None, "city": None, "pincode": None, "website": None, "industry": None, "product": None, "confidence": "low", "field_evidence": {}}],
  "contacts": [{"name": None, "company_name": None, "email_primary": None, "email_secondary": None, "phone_primary": None, "phone_secondary": None, "phone_country": None, "whatsapp": None, "position": None, "address": None, "city": None, "pincode": None, "website": None, "confidence": "low", "field_evidence": {}}],
  "emails": [{"file_name": None, "subject": None, "date": None, "sender_name": None, "sender_email": None, "receiver_name": None, "receiver_email": None, "to_emails": [], "cc_emails": [], "bcc_emails": [], "body_text": None, "has_signature": False, "contact_indices": []}],
  "call_logs": [],
  "unmapped_fields": [],
  "warnings": []
}
```

**BANNED_DB_KEYS** (LLM must never emit): id, uuid, created_at, updated_at, crm_contact_id, contact_id, company_id, source_email_id, session_id, extraction_run_id, user_id, processed_at, pushed_to_crm, dedup_status, created_by, file_path, email_key, phone_key, row_id, record_id.

**Evidence requirements**: Every non-null extracted field must have `field_evidence` with `excerpt` (non-empty string), `location`, and `confidence` (`high`/`medium`/`low`).

## Technical Stack

| Layer | Technology |
|---|---|
| **Framework** | FastAPI + uvicorn |
| **Language** | Python 3.12+ |
| **Database** | SQLite (unified `crm.db` + `eml.db`) with WAL mode, foreign keys |
| **Build** | PyInstaller + Inno Setup 6 (Windows .exe/.msi) |
| **Extraction** | - openpyxl (xlsx), xlrd (xls)<br>- pdfplumber (pdf, MIT)<br>- Python stdlib csv (csv)<br>- regex (txt, eml)<br>- Python `email` module (eml) |
| **LLM** | OpenRouter, Groq, Gemini, OpenAI, DeepSeek, Anthropic, Ollama (local) via provider chain |
| **Frontend** | Vanilla JS, native ES modules; no framework; no charts; WCAG 2.2 AA |
| **Styling** | CSS custom properties; warm neutrals `#F7F7F5`/`#1C1C1A`; accent `#2563EB`; Inter + IBM Plex Mono; 4/8px spacing; Lucide icons |
| **Testing** | pytest (27 tests); test data in `tests/` |
| **Env vars** | `PARSER_TIMEOUT` (default 15/30s), `PDF_MAX_PAGES` (default 200), `PORT` (default free port) |
| **Deployment** | Windows: PyInstaller + Inno Setup; Linux/macOS: venv development |

## Project Structure (Top-Level)

```
/.api/             — FastAPI route packages (settings, intake, jobs, staged, system)
/docs/            — Design decisions, acceptance spec, security review, user guide
/requirements*.txt — Python dependencies
/services/        — Core extraction logic
  /adapters/      — Per-format extractors (xlsx, csv, pdf, txt, eml)
  /dedup.py       — Duplicate detection engine (report only, no merge decisions)
  /eml_dedup_rules.py — Shared dedup normalizers (normalize_email, phone_key)
  /eml_processor.py — EML parsing (MIME, signature, field extraction)
  /contract.py    — Extraction result validation against crm-extraction.v1
  /prompts/       — Master system prompt + contract JSON (+ 5 source extensions)
  /validation.py  — Post-extraction field validator (spec §7, field matrix §5.1)
  __init__.py
/tests/           — pytest test suite (27 tests covering DB, adapters, contract, validation, dedup)
/app.py           — FastAPI composition root + server entry point
/build_windows.bat — Windows build script
/config.py        — Config load/save/lock-down, data directory
/CRM_Local.iss    — Inno Setup script
/CRM_Local.spec   — PyInstaller spec
/db.py            — Unified SQLite schema, migration train (v1–v10), dedup keys
/Gitignore/.gitignore
/DECISIONS.md     — Append-only decision register
/PRODUCT.md       — Product overview and positioning
/README.md        — User-facing documentation (this will be updated)
/SKILL_USAGE.md   — Skill usage tracking
/TASK_LOG.md      — Task execution log
/TEAM_BOARD.md    — Team board / coordination files
```

## Key Decisions Reference

All architectural and product decisions are recorded in `DECISIONS.md` in append-only format: `ID | date | decision | rationale | decider`. New decisions are never deleted; only appended.

Recent critical decisions (2026-11-07):

- **D-011**: `/api/config` retired; `/api/settings` becomes single config surface; mask `api_key` on ALL responses
- **D-010**: Router split into `api/` package; update `CRM_Local.spec` hiddenimports and CI test paths
- **D-030**: Migration train split — Phase 1 ships additive subset (v5c, v6, v7/write-path); v7 deferred to Phase 2
- **D-028**: Security P0 set — mask api_key on ALL four endpoints; add server-side sanitizer; Origin/Host validation
- **D-029**: Adopt QA's fix-ratchet — every confirmed-but-unfixed bug gets `xfail(strict=True)`

## Operational Guidelines

### For AI Agents Contributing to This Project

1. **Always read DECISIONS.md first** — recent rulings constrain what changes are permissible
2. **Never apply migrations on app startup** — `CRM_APPLY_MIGRATIONS=1` gate is enforced; app startups must NOT restructure production data
3. **API keys must never appear in logs, responses, or debug output** — masked per D-011 / SEC-01
4. **All extraction output validated against crm-extraction.v1 contract** — use `validate_extraction_result()` from `services/contract.py`
5. **Dedup keys must use shared normalizers** — `name_key()`, `company_key()`, `website_key()`, `email_key()` from `services/eml_dedup_rules.py` or `services/dedup.py`
6. **LLM prompts must follow build_prompt() pattern** — master prompt + source extension + contract + delimited untrusted content
7. **Header byte caps are SEC-10** — mirror byte-for-byte to CRM_Developer if modifying `services/eml_processor.py`
8. **Config.json perms: 0600 on POSIX** — `config._private()` + `config.lock_down()`
9. **No charts or graphs anywhere** — hard constraint from brief; tables, ranked lists, status badges only
10. **WCAG 2.2 AA** — semantic HTML, keyboard navigation, visible focus, screen-reader announcements

### Branch & Workflow Conventions

- **Feature branches**: `feature/xxx` or `bugfix/xxx`
- **Commits**: Conventional Commits recommended (but not enforced)
- **PRs**: Must pass `pytest -q`; security review for any API/db changes
- **Migration changes**: Require `CRM_APPLY_MIGRATIONS=1` + step-0 backup; app startups must not auto-apply
- **Breaking shape changes** (D-002, D-012): frontend updated in same PR as backend

### Environment Variables

| Var | Default | Description |
|---|---|---|
| `PORT` | auto-selected | Server port; 0 = auto-free-port |
| `PARSER_TIMEOUT` | 15 (xls) / 30 (pdf) | Seconds before parser times out |
| `PDF_MAX_PAGES` | 200 | Max pages to process in a single PDF |
| `WATCH_INTERVAL` | 30 | Seconds between folder scans (watch mode) |
| `THEME` | light | UI theme |

### Data Persistence

- **Config**: `%APPDATA%\CRM_Local\config.json` (JSON; 0600 on POSIX; masked api_keys)
- **CRM DB**: `%APPDATA%\CRM_Local\crm.db` (unified SQLite)
- **EML DB**: `%APPDATA%\CRM_Local\eml.db` (SQLite, may be migrated/merged)
- **Backups**: `backup_database()` uses sqlite3 backup API (WAL-safe); verifies with PRAGMA integrity_check
- **Restores**: `restore_database()` atomic replace with sidecar (WAL/SHM) cleanup

### Offline-First Guarantees

- All extraction Layer 1 (local pattern matching) works without any LLM/provider configured
- SQLite database is entirely local — no remote calls after initial setup
- Config stored locally; no cloud telemetry
- Exports (Excel/VCF/ZIP) generated locally
- Watch mode scans local folders only
- LLM enrichment is explicitly opt-in via provider chain configuration

## Related Projects

- **CRM_Developer** (`/home/kushal_jain/PROJECTS/CRM_Developer`) — Reference repository with cloud Supabase CRM; source for feature parity; cloud architecture (Supabase auth, Postgres, Render/Vercel) explicitly NOT migrated
- **docs/LOCAL_PRODUCT_STATUS.md** — Partially stale; re-verify all claims against source (D-001)
- **docs/USER_GUIDE.md** — User-facing guide (may need updating)
- **SKILL_USAGE.md** — Skill usage tracking log