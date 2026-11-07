# Handover — CRM Local

This document summarizes the current state of the CRM Local project, what has been done, and what contributors need to know to continue development.

## Project Status (2026-11-07)

- **Core app**: FastAPI + uvicorn server (`app.py`) running loopback-only on `127.0.0.1`
- **Database**: Unified SQLite (`crm.db` + `eml.db`) with migration train v1–v10
- **Extraction**: 6 format adapters (xlsx, xls, csv, pdf, txt, eml) → local pattern matching + optional LLM enrichment
- **Staging**: `staged_contacts` table for human-review-before-commit workflow (D-030)
- **API**: `/api` routes — system, settings, intake, jobs, staged-contacts
- **Build**: PyInstaller + Inno Setup for Windows `.exe`/`.msi`; venv development on Linux/macOS
- **Tests**: 27 pytest tests covering DB, adapters, contract validation, migration logic

## Recent Decisions (DECISIONS.md)

| ID | Date | Decision |
|---|---|---|
| D-001 | 2026-11-07 | Master brief is single source of truth; re-verify all audit docs against source |
| D-011 | 2026-11-07 | `/api/settings` becomes single config surface; `/api/config` retired; mask `api_key` on all settings responses |
| D-010 | 2026-11-07 | Router split: routes move into `api/` package; update `CRM_Local.spec` hiddenimports and CI test paths |
| D-030 | 2026-11-07 | Migration train split: Phase 1 ships additive subset (v5c, v6, v7/write-path redirection); v7 deferred to Phase 2 |
| D-028 | 2026-11-07 | Security P0 set: mask api_key on ALL four config/settings endpoints; add server-side sanitizer; Origin/Host validation middleware |
| D-029 | 2026-11-07 | Adopt QA's fix-ratchet: every confirmed-but-unfixed bug gets `xfail(strict=True)` test |

## Open Questions / TODOs

- **D-005**: Two "supplied database diagrams" not present — must not fabricate; spec §3 field tables are authority
- **D-004**: Coordination files at repo root; three of six boards deferred until their first real content exists
- **Migration gate**: `CRM_APPLY_MIGRATIONS=1` must be set to apply migrations on the live DB; app startups/tests/CI must never restructure production data by accident
- **Phase 2**: Write-path redirection, `eml_contacts` → VIEW, FTS5 search, default import policy decision
- **Security**: Mirror SEC-10 header caps from CRM_Local to CRM_Developer services/eml_processor.py (byte-for-byte)

## Architecture Deep Dives

### Migration System (`db.py`)

- `init()` creates all tables, runs `_migrate()` (ensure columns + migrate eml data), then `run_migrations()`
- `run_migrations()` is gated: unless `CRM_APPLY_MIGRATIONS=1` and the DB is the live file, pending migrations are logged but NOT applied
- Each migration runs in its own explicit transaction with rollback on failure
- Migrations are registered via `_Migration` class with version, name, fn, rollback_sql, fk_off flag
- **Current version**: `CURRENT_MIGRATION_VERSION = 10`
- **Migration list**: `_MIGRATIONS` dict (v1–v10), see `db.py` for each migration function

### Extraction Contract (`services/prompts/contact_extraction.py`)

- **MASTER_SYSTEM_PROMPT** + **EXTRACTION_CONTRACT** (JSON, `crm-extraction.v1`)
- Five **SOURCE_EXTENSIONS** (spec §6.3): spreadsheet, pdf, csv, txt, eml
- `build_prompt()` assembles `[system, user]` messages: master prompt + source extension, then contract + delimited untrusted content
- `validate_extraction_result()` in `services/contract.py` gates payload — whole-payload acceptance only, never partial strip-down
- **BANNED_DB_KEYS** — LLM must never emit: id, uuid, created_at, updated_at, crm_contact_id, contact_id, company_id, source_email_id, session_id, extraction_run_id, user_id, processed_at, pushed_to_crm, dedup_status, created_by, file_path, email_key, phone_key, row_id, record_id

### Staged Contact Workflow (D-030)

1. **Extract** → `staged_contacts` via any adapter (local Layer 1 only; LLM enrichment handled by orchestrator)
2. **Review**: UI shows staged contacts with three status dimensions (review_status, dedup_status, import_status)
3. **Approve** (`POST /api/staged-contacts/approve`): Upsert to `contacts` (local-wins: only overwrite empty fields); set `review_status='APPROVED'`, `import_status='NEW_CONTACT_CREATED'`
4. **Reject** (`POST /api/staged-contacts/{id}/reject`): Set `review_status='REJECTED'`, `import_status='IMPORT_FAILED'`
5. **Dismiss** (`POST /api/staged-contacts/{id}/dismiss`): Set `review_status='DISMISSED'`, `import_status='NOT_IMPORTED'`
6. **Merge** (`POST /api/staged-contacts/{id}/merge`): Local-wins merge with existing contact; if no existing, create new

### File Adapters

Each adapter (`services/adapters/*.py`) implements:
- `can_handle(path) → bool` — checks file extension
- `extract(path) → ExtractionResult` — returns `contacts` list + `adapter` name + `local_only=True`

Results flow: adapter → `merge_fields(local, ai)` → `validate_extraction_result()` → `staged_contacts` insert.

### API Routes (summary)

| Route | Description |
|---|---|
| `GET /api/health` | Liveness probe |
| `GET /api/status` | Counts, pending, run state, providers, version |
| `GET /api/settings` | Masked config (chain masked) + db paths |
| `POST /api/settings` | Update config (chain merge, provider add/patch/remove) |
| `GET /api/providers` | Masked provider chain |
| `POST /api/providers` | Add provider |
| `PATCH /api/providers/{id}` | Edit provider |
| `DELETE /api/providers/{id}` | Remove provider |
| `GET /api/providers/{id}/enable/disable` | Toggle provider |
| `POST /api/intake` | Universal multipart intake: 6 formats → job |
| `GET /api/jobs` | In-memory job registry (Phase 2 stub) |
| `GET /api/staged-contacts` | List with filtering/pagination |
| `GET /api/staged-contacts/{id}` | Get single staged contact |
| `POST /api/staged-contacts/approve` | Upsert to CRM contacts |
| `POST /api/staged-contacts/bulk-action` | Bulk approve/reject |
| `POST /api/staged-contacts/{id}/reject` | Reject staged contact |
| `POST /api/staged-contacts/{id}/dismiss` | Dismiss staged contact |
| `POST /api/staged-contacts/{id}/edit` | Edit staged contact fields |
| `POST /api/staged-contacts/{id}/merge` | Merge with existing CRM contact |
| `GET /api/staged-contacts/dedup-check` | Check duplicates |
| `GET /api` | System status |

## Coding Conventions

- **Python 3.12+**, typing where practical but not obsessive
- FastAPI routes in `api/` package; composition root in `app.py`
- DB: `db.py` — unified schema, migration train, dedup keys (`name_key`, `company_key`, `website_key`, `email_key`, `phone_key`)
- Adapters: `can_handle()` + `extract()` — all `local_only=True`; LLM enrichment separate
- Contract: `services/prompts/contact_extraction.py` — master prompt + shared JSON contract
- Validation: `services/validation.py` — reports issues, never mutates raw values
- Dedup: `services/dedup.py` — reports match bands, never decides merge
- All new code goes through `pytest` suite: `venv/bin/python -m pytest -q`
- Env vars: `PARSER_TIMEOUT` (default 15/30s), `PDF_MAX_PAGES` (default 200)
- **Never** hardcode API keys or secrets in source; use `config.json` with 0600 perms (D-011 / SEC-01 / SEC-04)
- **Windows-only** features (autostart, Inno Setup) guarded by `os.name != "nt"` or `getattr(sys, "frozen", False)`

## Debugging Hotspots

1. **`intake.py:78`** — NameError reported in D-028; tighten per D-028
2. **`config.json` perms** — must be 0600 on POSIX (D-011 / SEC-09); `_private()` + `lock_down()` in `config.py`
3. **`/api/config` retired** → use `/api/settings`; confirmed secrets leak (`chain[].api_key` → browser JS) fixed by this
4. **Migration gate** — `CRM_APPLY_MIGRATIONS=1` required; app startups must NOT auto-apply
5. **Origin/Host validation** — loopback only (D-028 / SEC-03); foreign Origin rejected before Host considered
6. **`services/eml_processor.py`** — header byte caps (SEC-10); mirror byte-for-byte to CRM_Developer

## Local Development Workflow

```bash
# 1. Create venv
python -m venv venv

# 2. Install deps
venv/bin/pip install -r requirements-dev.txt

# 3. Run app
venv/bin/python app.py

# 4. Test suite
venv/bin/python -m pytest -q

# 5. Make changes, re-run tests

# 6. When done, ship:
#    - build_windows.bat (Windows)
#    - or venv/python on Linux/macOS for dev
```

## Known Issues (from DECISIONS.md & QA)

- `intake.py:78` NameError (to be fixed in D-028 batch)
- Two supplied database diagrams not present — verify against spec §3 field tables
- `LOCAL_PRODUCT_STATUS.md` has at least one provably false claim (`services/extraction.py` absent) — re-verify all claims
- QA ratchet: confirmed-but-unfixed bugs get `xfail(strict=True)`; green suite must not hide known defects

## Getting Unstuck

1. Run `venv/bin/python -m pytest -q` to see which tests fail
2. Check `DECISIONS.md` for recent rulings that may constrain your changes
3. If touching migrations: remember `CRM_APPLY_MIGRATIONS=1` gate + step-0 backup
4. If touching API: check `INTERFACE_CONTRACTS.md` §2.1 for route contracts
5. If adding a new format adapter: follow the pattern in `services/adapters/` — `can_handle()` + `extract()` → `ExtractionResult`
6. If adding LLM enrichment: follow `build_prompt()` + `validate_extraction_result()` pattern