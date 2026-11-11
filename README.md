# CRM Local

A Windows desktop app that reads two folders on your machine, extracts business contacts, and keeps them in local databases. No accounts, no cloud database, no hosting. The only network traffic is the LLM provider you configure.



## What it does

- **One unified database** — `crm.db` holds everything: contacts, companies, emails, files ledger, staged review queue, extraction runs, provenance and dedup keys.
- **Staged review** — extracted contacts never enter the CRM until you approve them; duplicates, conflicts and invalid values are flagged, not hidden.
- **Folder scan (optional)** — `.xlsx`, `.xls`, `.csv`, `.pdf` from a CRM folder and `.eml` from an EML folder can be scanned in date order; re-scans skip unchanged files.
- Every processed file is recorded in a ledger, so a rescan never processes the same file twice.
- Contacts are shown as a sheet inside the app and can be downloaded as a styled Excel file at any time.
- Staged contacts go through review/approval before entering the canonical CRM database.
- Full source provenance and evidence tracking for every extracted field.

## Install

1. Run `CRM_Local-Setup.exe` (or `CRM_Local.exe` for a portable copy).
2. The app opens in your browser at `http://127.0.0.1:<port>`.
3. On **Extract**, drop CSV/XLSX/XLS/PDF/TXT/EML files — extraction is staged for review.
4. Open **Staged review** to approve, edit, reject or dismiss each extracted contact.

Windows SmartScreen may warn about an unsigned installer. Choose **More info → Run anyway**. Installation is per-user and needs no admin rights; uninstalling does not delete your data in `%APPDATA%\CRM_Local\`.

## Settings

### Providers

Extraction runs in two layers:

1. **Local pattern matching** (always on, no setup).
2. **Your provider chain**, tried top to bottom. If one fails, the next takes over.

Add providers in **Settings → Add provider**. Cloud APIs are the default:

| Provider | Model example |
|---|---|
| OpenRouter | `anthropic/claude-3.5-sonnet` |
| Groq | `llama-3.3-70b-versatile` |
| Gemini | `gemini-2.0-flash` |
| OpenAI | `gpt-4o-mini` |
| DeepSeek | `deepseek-chat` |
| Anthropic | `claude-3-5-sonnet-latest` |
| Ollama | any local model, host default `http://localhost:11434` |

Use the arrows to reorder. Leave the chain empty to use local matching only.

### Watch mode

While the app is open, it scans both folders on an interval (default 30 s). **Start CRM Local when Windows starts** adds a shortcut to your Startup folder — available in the installed app.

## Where your data lives

```
%APPDATA%\CRM_Local\
  config.json   (settings + provider keys, owner-only)
  crm.db        (your entire CRM)
```

Back up that folder by copying it. Deleting it resets the app.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Server                          │
│  (app.py — localhost:8000, loopback only, no auth)             │
├─────────────────────────────┬─────────────────────────────────┤
│                            │                                 │
│      ┌─────────────────┐    ┌─────────────────────────┐      │
│      │   Adapters      │    │   Services              │      │
│      │ (xlsx, csv,    │    │ (eml_processor, dedup,  │      │
│      │ pdf, txt)       │    │ validation, contract)   │      │
│      └─────────────────┘    └─────────────────────────┘      │
│            ▲                   ▲               ▲              │
│            │                   │               │              │
│      ┌─────────────────┐    ┌─────────────────────────┐      │
│      │    DB Layer     │    │   Extraction Contract  │      │
│      │ (sqlite3,       │    │ (crm-extraction.v1)    │      │
│      │ migrations)     │    └─────────────────────────┘      │
│      └─────────────────┘                                 │
│                unified SQLite DB (crm.db)       │
└─────────────────────────────────────────────────────────────────┘
```

### Key Components

- **Adapters** (`services/adapters/`) — Per-format extractors (xlsx, csv, pdf, txt, eml). Each implements `can_handle()` and `extract()`.
- **Services** (`services/`) — Core logic: `eml_processor.py` parses .eml files; `dedup.py` reports duplicate matches; `validation.py` validates extracted fields; `contract.py` gates AI output against the shared schema.
- **Contract** (`services/prompts/contact_extraction.py`) — The master system prompt + `crm-extraction.v1` JSON contract shared by all extraction sources. Five source-specific extensions (spec §6.3).
- **DB** (`db.py`) — Unified SQLite schema with `contacts`, `companies`, `eml_emails`, `eml_contacts`, `staged_contacts`, and migration train (v1–v10). D-030 gate: migrations apply only with `CRM_APPLY_MIGRATIONS=1`.
- **API** (`api/`) — FastAPI routes under `/api`: system/health, status, settings/providers, intake, jobs, staged-contacts, and autostart (Windows-only).

## Build from source

Requires Python 3.12+ on Windows.

### Windows (PyInstaller + Inno Setup)

```bat
build_windows.bat
```

Produces `dist\CRM_Local.exe` and, if Inno Setup 6 is installed, `dist\CRM_Local-Setup.exe`.

### Linux/macOS for development

```bash
python -m venv venv
venv/bin/pip install -r requirements-dev.txt
venv/bin/python app.py
venv/bin/python -m pytest -q
```

The Windows `.exe` cannot be cross-compiled from Linux; use the GitHub Actions workflow (`.github/workflows/windows-build.yml`) or a Windows machine.

## Requirements

```
requirements.txt  — runtime dependencies
requirements-dev.txt  — includes pytest for testing
```

## Data Model Highlights

### Contacts table

| Field | Description |
|---|---|
| `id` | Primary key |
| `company_id` | FK → companies (ON DELETE SET NULL) |
| `name`, `email_primary`, `email_secondary` | Contact identification |
| `phone_primary`, `phone_secondary`, `phone_country` | Phone numbers |
| `company`, `designation`, `address`, `city`, `pincode`, `website` | Address data |
| `whatsapp`, `position` | Optional contact methods |
| `source_file`, `source_row`, `extraction_run_id` | Provenance |
| `field_origin`, `email_key`, `phone_key` | Dedup keys |
| `created_at`, `updated_at` | Timestamps |

### Staged contacts (D-030)

New `staged_contacts` table holds extraction results pending human review. Three independent status dimensions:

- **review_status**: NEW → NEEDS_REVIEW → READY/APPROVED/REJECTED/DISMISSED
- **dedup_status**: NOT_CHECKED → UNIQUE/EXACT_DUPLICATE/PROBABLE_DUPLICATE/CONFLICT
- **import_status**: NOT_IMPORTED → NEW_CONTACT_CREATED/EXISTING_CONTACT_ENRICHED/IMPORT_FAILED

All 17 fields from `eml_contacts` are preserved in `staged_contacts.raw_source_data` (JSON). Write path is redirected: ALL canonical upserts go through staging approval or the Smart Import policy gate.

### CHECK constraints on staged_contacts

```sql
review_status IN ('UNVALIDATED','VALID','INVALID')
dedup_status IN ('NOT_CHECKED','UNIQUE','EXACT_DUPLICATE','PROBABLE_DUPLICATE','CONFLICT')
import_status IN ('NOT_IMPORTED','NEW_CONTACT_CREATED','EXISTING_CONTACT_ENRICHED','IMPORT_FAILED')
```

## Migration Train (D-030)

Migrations apply in order v1→v10. Fresh installs self-provision the full schema on first launch. Databases that already contain data are gated: migrations run only with `CRM_APPLY_MIGRATIONS=1` (or an explicit support step), after a backup. Ships the additive subset:

- **v5c**: Status backfills + warnings on staged_contacts
- **v6**: `contacts` rebuild (real FKs + dedup keys, step-0 backup + count verification); `position` backfilled from `designation`
- **v7**: `eml_contacts` → VIEW (deferred to Phase 2, ships same release as write-path redirection)
- **v8**: FTS5 (Phase 5)
- **v9**: Verify and log structural integrity
- **v10**: Drop empty `records` table

## Security Overview (D-028 / SEC-01 through SEC-10)

- **SEC-01**: `api_key` masked on ALL `/api/config`, `/api/settings` endpoints + `app.py` config responses
- **SEC-02**: Server-side sanitizer stopgap for `innerHTML` sinks (Phase 6 CSP)
- **SEC-03**: Origin/Host validation middleware for loopback (blocks cross-site POSTs + DNS-rebinding)
- **SEC-04**: Provider chain never echoes raw keys in any response
- **SEC-05**: Server receives bytes, never filesystem paths (universal intake)
- **SEC-06**: Prompt content capped and delimited (MAX_CONTENT_CHARS, UNTRUSTED markers)
- **SEC-07**: EML header byte caps (subject ≤200, headers ≤100, key ≤40)
- **SEC-08**: LLM never emits DB-owned fields (id, timestamps, crm_contact_id, etc.)
- **SEC-09**: `config.json` forced to 0600 at startup
- **SEC-10**: Header caps in `services/eml_processor.py` mirrored to `CRM_Developer`

## Extractor Details

| Format | Adapter | Key Logic |
|---|---|---|
| `.xlsx` | `services/adapters/xlsx.py` (via `services/adapters/_table.py` + `parse.py`) | openpyxl; per-sheet header mapping by meaning (merged cells, multi-row headers) |
| `.xls` | `services/adapters/xls.py` (via `services/parser.py`) | xlrd; skips lookup/index sheets; date-cell conversion |
| `.csv` | `services/adapters/csv.py` | utf-8-sig; delimiter sniffing; header-by-meaning mapping |
| `.pdf` | `services/adapters/pdf.py` (via `services/parser.py`) | PyMuPDF table extraction; labeled-line fallback paired per record |
| `.txt` | `services/adapters/txt.py` | Phones/emails per line; best-effort names from separators |
| `.eml` | `services/adapters/eml.py` (via `services/eml_processor.py`) | MIME stdlib parsing; signature detection; From-header display name wins |

## Extraction Pipeline

```text
File Scan
    ↓
Adapter (format-specific extractor)
    ↓
Layer 1: Local field extraction (regex/pattern matching)
    ↓
Layer 2: Optional LLM enrichment (OpenRouter / provider chain)
    ↓
validate_extraction_result() against crm-extraction.v1 contract
    ↓
Store in staged_contacts (pending review)
    ↓
Human: Review → Approve/Reject
    ↓
Upsert to contacts/companies (local-wins: only overwrite empty fields)
    ↓
Export: styled Excel download, VCF/ZIP generation
```

## Export

- **CSV** — contacts and emails export client-side from the current view
  (respecting filters/selection) with formula-injection protection.
- **Excel (.xlsx)** — styled workbook generated server-side (`export.py`),
  with the same formula-injection protection.

VCF, ZIP and PDF report exports are not in this release.

## Privacy & Data Policy

- **No cloud**: All processing happens locally on your machine
- **No accounts**: No user accounts, no authentication
- **Secrets never exposed**: `api_key` values are masked in all API responses (D-011, SEC-01)
- **Local-first**: Fully functional offline; external LLM enrichment is opt-in only
- **Source truth preserved**: Raw records, original emails, and provenance are never discarded
- **Formula-injection protection**: Excel exports protect against formula injection

## Accessibility

WCAG 2.2 Level AA required: semantic HTML, keyboard navigation, visible focus, screen-reader announcements, accessible drawers/dialogs, reduced-motion support, accessible exports.

## License

License terms have **not** been provided with this release — do not
redistribute publicly until the project owner adds a `LICENSE` file. See
`THIRD_PARTY_NOTICES.md` (PyMuPDF AGPL-3.0 / Artifex commercial dual
license) before distributing to clients.