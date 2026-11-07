# CRM Feature Parity — CRM_Local (target) ↔ CRM_Developer (reference)

**Date:** 2026-11-07
**Author:** systems-architect (Round 1, read-only investigation)
**Target HEAD:** `7610095` — "unified database, security fixes, extraction adapters, universal intake, settings, 9-view frontend, CI"
**Method:** every claim below was verified against source in this session. Line numbers are from the files as they exist at HEAD. The two prior audit docs (`docs/IMPLEMENTATION_REPOSITORY_AUDIT.md`, `docs/LOCAL_PRODUCT_STATUS.md`, both 2026-11-06) are treated as hypotheses and are graded in §3.3.

**Executive summary:** CRM_Local is a working *extraction* app with a 9-view shell, a unified 11-table SQLite DB, and a real adapter/intake layer. It is **not yet a CRM workspace**: of the 13 required navigation areas, 5 exist as views (Dashboard/Overview, Import Center/Extract, Contacts, Data Quality, Processing History, Settings — 6 counting Settings), 7 are absent (Review Queue, Companies, Calls & Activities, Duplicates, Reports & Exports, Help & Shortcuts, plus a working Emails browser), and the existing Dashboard KPIs are largely placeholders rather than DB-derived values. The reference repository is itself **weaker than the brief** on several rows (no server-side contacts list, no companies view, no saved views/tags/command palette/global search), so a number of required capabilities are net-new rather than ports.

---

## 1. Verified current state of CRM_Local

### 1.1 HTTP routes (all in `app.py` — the only route file)

| Method | Path | Handler | Evidence | Notes |
|---|---|---|---|---|
| GET | `/` | `index` | `app.py:85` | serves `static/index.html` |
| GET | `/api/status` | `status` | `app.py:90` | counts + pending + run snapshot + providers |
| GET | `/api/config` | `get_config` | `app.py:106` | **returns `chain` incl. `api_key` to the browser** |
| POST | `/api/config` | `set_config` | `app.py:115` | writes config.json, toggles watcher |
| POST | `/api/scan` | `start_scan` | `app.py:128` | background `pipeline.scan(which)` |
| POST | `/api/intake` | `universal_intake_endpoint` | `app.py:136` | JSON `{paths:[...]}`, max 50 files |
| GET | `/api/jobs/{job_id}` | `get_job_status` | `app.py:148` | **stub** — always `state:"done"` |
| POST | `/api/jobs/{job_id}/cancel` | `cancel_job` | `app.py:154` | **stub** — always `cancelled` |
| GET | `/api/settings` | `get_settings` | `app.py:160` | duplicate of `/api/config` (no path info) |
| POST | `/api/settings` | `update_settings` | `app.py:166` | duplicate of `/api/config` |
| GET | `/api/contacts` | `contacts` | `app.py:175` | `which, q, page, size`; no sort/filter params |
| PATCH | `/api/contacts/{which}/{id}` | `edit_contact` | `app.py:186` | arbitrary `fields` dict → **no allow-list** |
| DELETE | `/api/contacts/{which}/{id}` | `remove_contact` | `app.py:200` | |
| GET | `/api/export` | `export_contacts` | `app.py:214` | **XLSX only**, no filter/selection |
| POST | `/api/pick-folder` | `pick_folder` | `app.py:231` | tkinter native dialog (`pipeline.py:297`) |
| POST | `/api/open-folder` | `open_folder` | `app.py:239` | |
| POST | `/api/test-llm` | `test_llm` | `app.py:253` | |
| POST | `/api/autostart` | `set_autostart` | `app.py:263` | Windows-only, frozen-exe-only |
| — | `/static/*` | StaticFiles mount | `app.py:286` | |
| — | security-headers middleware | | `app.py:32-38` | nosniff / DENY / referrer |
| — | startup: `db.init()` + watcher | | `app.py:78-82` | |
| — | `openapi_url=None` | | `app.py:30` | |
| — | `main()` binds `127.0.0.1`, free port 8000-8010, opens browser when frozen | | `app.py:301-311`, `_free_port` `app.py:289` | |

**Absent routes (required by the brief):** no `/api/emails`, `/api/companies`, `/api/calls`, `/api/duplicates`, `/api/quality`, `/api/history` (processing), `/api/search`, `/api/reports`, `/api/undo`, `/api/help`, no bulk endpoints, no saved-views/tags/notes/follow-ups endpoints, no staging/approve/reject endpoints.

### 1.2 Frontend (`static/` — `index.html` 206 lines, `app.js` 374 lines, `style.css` 133 lines)

Nav items at `static/index.html:17-25`; view containers (9):

| # | View id | Container | Loader in `app.js` | State |
|---|---|---|---|---|
| 1 | `overview` | `index.html:38` | `loadOverview` `app.js:50` | **KPIs are placeholders** — `counts.processed_files`, `counts.new`, `counts.duplicates` are never returned by `db.counts()` (`db.py:514-520` returns only `crm/eml/eml_contacts/emails`), so Files/Duplicates render 0 or fall back to the contact count (`app.js:56-58`); completeness is hardcoded to 100% (`app.js:60-61`); "Recent Activity" is a static string (`app.js:62`) |
| 2 | `extract` | `index.html:55` | `startExtraction` `app.js:101` | 6-format dropzone (`index.html:59-60`), queue + progress; **sends bare file names, not paths** (`app.js:114` → `intake.py:40` `os.path.exists` fails) |
| 3 | `contacts` | `index.html:76` | `loadContacts` `app.js:137` | server pagination + `q` search; **sort is a no-op** (`sortContacts` `app.js:179` never sends `sort` to the API); `filterContacts` (`index.html:80`) and `exportContacts` (`index.html:86`) are **referenced but not defined** in `app.js`; edit is a `prompt()` (`app.js:185`) |
| 4 | `emails` | `index.html:104` | `loadEmails` `app.js:211` | **stub** — renders "Email browser requires backend endpoint" (`app.js:216`); no `/api/emails` exists |
| 5 | `profiles` | `index.html:124` | `loadProfiles` `app.js:229` | flat cards of first 100 contacts |
| 6 | `analytics` | `index.html:130` | `loadAnalytics` `app.js:246` | four `chart-*` divs rendered as **plain text lines** (`app.js:253-268`); no chart library present; view name/ids conflict with the "no charts anywhere" rule |
| 7 | `quality` | `index.html:141` | `loadQuality` `app.js:275` | client-side regex over first 1000 rows; duplicates card is a placeholder ("use Contacts view for manual review", `app.js:286`) |
| 8 | `history` | `index.html:152` | `loadHistory` `app.js:293` | **stub** — single row "Processing history available via /api/status" (`app.js:296`) |
| 9 | `settings` | `index.html:168` | `loadSettings` `app.js:303` | provider chain list, folders, theme, watch; add/remove provider via `prompt()` (`app.js:321-341`) |

Other frontend facts: hash routing (`app.js:24`, `31-34`, `368-375`); inline global `onclick=` handlers throughout `index.html` (e.g. `index.html:17`); **not** an ES module (`index.html:205` plain `<script src>`); no `keydown` handler anywhere (no command palette, no shortcuts); a11y = `focus-visible` (`style.css:121`), `prefers-reduced-motion` (`style.css:125`), `aria-label` on sidebar/hamburger (`index.html:14,16,30`); **no skip link**.

### 1.3 Modules and responsibilities

| Module | Lines | Responsibility | Key evidence |
|---|---|---|---|
| `app.py` | 315 | All HTTP routes, security headers, PyInstaller windowed-exe guard, uvicorn entry | `app.py:9-11`, `301-311` |
| `config.py` | 60 | `config.json` defaults/load/save; `data_dir()` (`%APPDATA%/CRM_Local` or `~/.crm_local`); `db_path()` | `config.py:8-18`, `21-37` |
| `db.py` | 535 | Unified SQLite (`_UNIFIED_DB = "crm.db"` `db.py:11`), schema, idempotent column migration, data migration from legacy `eml.db`, dedup index, CRUD | `init` `db.py:27-49`, schema `db.py:52-168` |
| `intake.py` | 128 | **Dropzone path**: mixed-format batch → adapter → (EML: local+LLM merge) → `db.upsert_contact(..., "contacts")` | `universal_intake` `intake.py:25`, caps `intake.py:14-17`, magic bytes `intake.py:19-22,54-59` |
| `pipeline.py` | 316 | **Folder path**: recursive scan, processed-file ledger, EML date-ordered processing, doc header mapping, watcher loop, native folder picker | `scan` `pipeline.py:210`, `_process_eml` `pipeline.py:116`, `_process_doc` `pipeline.py:174`, `_watch_loop` `pipeline.py:273`, `folder_picker` `pipeline.py:297` |
| `llm.py` | 176 | Provider failover chain (7 providers incl. Ollama), JSON output validation, `test_entry`, key redaction | `PROVIDERS` `llm.py:26`, `extract` `llm.py:147`, `parse_json` validation `llm.py:47-73`, `_redact` `llm.py:142` |
| `parse.py` | 188 | Header→field alias mapping with confidence, row cleaning, xlsx/csv readers | `ALIASES` `parse.py:18`, `map_headers` `parse.py:45`, `row_to_contact` `parse.py:174` |
| `export.py` | 55 | XLSX only, styled, **formula-injection sanitize** | `contacts_to_xlsx` `export.py:24`, `_sanitize` `export.py:37-40` |
| `services/adapters/` | 83+6×~50 | `NormalizedContact`/`ExtractionResult` dataclasses, adapter protocol + registry, 6 adapters (xlsx, xls, csv, pdf, txt, eml) | `services/adapters/__init__.py:12,36,45,58-78` |
| `services/parser.py` | 302 | XLS (xlrd) + PDF (PyMuPDF) table parsing | `parse_xls` `services/parser.py:7`, `parse_pdf` |
| `services/eml_processor.py` | 287 | EML parse, local field extraction, **prompt-injection wrapping**, local-wins merge | `build_llm_prompt` `services/eml_processor.py:262-273` |
| `services/eml_dedup_rules.py` | 47 | `is_duplicate`, `phone_key`, normalizers | `services/eml_dedup_rules.py:21-47` |
| `static/` | 713 | Vanilla JS SPA shell (9 views) | see §1.2 |

**Parallel/conflicting implementations already present (relevant to the one-of-everything rule):**

- Two ingestion paths with different behaviour: folder scan (`pipeline.scan`) vs dropzone (`intake.universal_intake`). Intake **never** writes `eml_emails`, `eml_contacts`, or `processed_files` (`intake.py:93-120` only calls `db.upsert_contact(..., "contacts")`), so an EML dropped into the UI produces **no email row** and never appears in the Emails view or the staging table, and is not ledger-marked (the folder scanner will process it again later).
- Two header-mapping implementations: rich alias table in `parse.map_headers` (`parse.py:45`) vs naive substring matching duplicated in 4 adapters (`services/adapters/csv.py:26-46`, `xlsx.py:34-51`, `xls.py:25-43`, `pdf.py:22-40`). The same CSV file yields different contacts depending on whether it arrived via folder scan or dropzone.
- Two dedup implementations: `db.DedupIndex` (`db.py:345-388`) vs `services/eml_dedup_rules.is_duplicate` (imported by `intake.py:9` but **never called** there — intake relies solely on `db.upsert_contact`/`_find` `db.py:391-406`).
- Two config endpoints writing the same file: `/api/config` (`app.py:106,115`) and `/api/settings` (`app.py:160,166`).
- `db.connect()` is defined three times (`db.py:18`, `db.py:295`, `db.py:330`) with dead aliases `connect_crm`/`connect_eml` (`db.py:291-292`) — last definition wins.
- **Latent bug:** `intake.py:78` calls `llm.extract(...)` but `intake.py:10` only does `from llm import parse_json as parse_llm_json`, so `llm` is unbound → `NameError` on any EML intake *when a chain is passed*. Currently unreachable because `app.py:144` calls `intake.universal_intake(file_paths)` with `chain=[]`; untested (`tests/test_intake.py` covers csv/empty/unsupported only).
- **Secrets exposure:** `GET /api/config` returns the full config including `chain[].api_key` (`app.py:106-112`), which the browser JS receives (`app.js:305`, `327-330`). This violates the brief's "secrets NEVER exposed to browser JS".

### 1.4 Database tables (`db.py:52-168`, single file `crm.db`)

| Table | Evidence | Notable columns | Written by code? |
|---|---|---|---|
| `companies` | `db.py:54` | name, address, city, pincode, website, industry, product, created/updated_at; FK target of `contacts.company_id` | **NO** — no `INSERT INTO companies` anywhere in the repo |
| `contacts` | `db.py:63` | company_id, name, email_primary/secondary, phone_primary/secondary, phone_country, company (free text), designation, address, city, pincode, website, whatsapp, position, files, products_misc, **source_file, source_row, extraction_run_id, field_origin, email_key, phone_key**, created/updated_at; 9 indexes `db.py:75-82` | yes (`upsert_contact` `db.py:409`) — but **only `source_file` of the provenance set is populated**; `source_row`/`field_origin`/`extraction_run_id` are dropped by `intake.py:94-105` and never set by `pipeline.py` |
| `call_logs` | `db.py:84` | call_date, duration_minutes, call_type, outcome, notes, next_action, next_action_date, created_by | **NO** — schema only |
| `users` | `db.py:96` | email, provider_uid, last_login | **NO** (local single-user; keep for compatibility) |
| `session_data` | `db.py:104` | file_name, sheet_name, upload_date, **mapping**, total_records, imported, skipped, is_active | **NO** — schema only (reference writes it on import) |
| `records` | `db.py:113` | session_id FK, data (JSON blob) | **NO** |
| `eml_emails` | `db.py:121` | file_name, file_path, subject, date, sender, to/cc/bcc_emails, body_text, has_signature, signature_block, processed_at | yes (`insert_email` `db.py:443`, folder-scan path only) |
| `eml_contacts` | `db.py:132` | source_email_id, contact fields, **dedup_status**, **pushed_to_crm**, crm_contact_id, to/cc/bcc, field_origin, email_key, phone_key | yes (`insert_eml_contact` `db.py:459`, `mark_pushed` `db.py:476`, folder-scan path only) |
| `processed_files` | `db.py:150` | path PK, size, mtime, status, detail, contacts_found, processed_at | yes (`mark_processed` `db.py:529`) |
| `extraction_runs` | `db.py:155` | started/completed, status, files_processed, contacts_found, error, config_snapshot | **NO** — no `create_extraction_run` equivalent exists in the target |
| `_migration_log` | `db.py:164` | version, name, applied_at, rollback_sql, checksum | yes (one row, `db.py:197`) |

Connection settings: WAL + `foreign_keys=ON` (`db.py:22-23`). Legacy `eml.db` → unified migration is best-effort and idempotent (`db.py:216-287`).

### 1.5 Test inventory — 58 test functions across 10 files; **58 passed in 181.5s** (run this session)

| File | # tests | Covers |
|---|---|---|
| `tests/test_adapters.py` | 16 | dispatch/registry for all 6 formats, dataclass defaults, txt/csv/eml adapter extraction |
| `tests/test_app.py` | 7 | `/`, `/api/status`, `/api/config`, `/api/contacts`, invalid `which`, `/api/pick-folder`, `/api/settings` |
| `tests/test_db.py` | 4 | enrich-without-overwrite, `phone_key`, `DedupIndex`, ledger idempotency |
| `tests/test_dedup_rules.py` | 4 | normalizers, `is_duplicate`, index load |
| `tests/test_export.py` | 2 | styled sheet + headers, empty rows |
| `tests/test_intake.py` | 3 | csv happy path, empty, unsupported |
| `tests/test_llm.py` | 5 | JSON fence stripping, chain failover, disabled entries, empty chain, Ollama endpoint |
| `tests/test_llm_validation.py` | 8 | field limits, invalid email, nulls, lists, `_redact` |
| `tests/test_parse.py` | 6 | csv/xlsx mapping, secondary-column precedence, identity drop, float phones, confidence |
| `tests/test_pipeline.py` | 5 | EML scan + CRM push, idempotent rescan, date order, local-wins, missing folder |

**Coverage gaps vs the brief:** no tests for `/api/intake` endpoint wiring (only the function), no tests for jobs stubs, no tests for `/api/autostart` or `/api/test-llm`, no tests for EML+chain intake path (the `NameError` above), no security/prompt-injection test suite in the target, no coverage gate in CI (`.github/workflows/ci.yml` runs `pytest tests/ -q` only).

### 1.6 Local-specific features to preserve (verified present)

Folder watching (`pipeline.py:273-295`), processed-file ledger (`db.py:523-536`), native folder dialogs (`pipeline.py:297-316`), typed-path fallback when the picker is unavailable (commit `790ea1e`), Ollama provider (`llm.py:82-92`), PyInstaller windowed-exe guard + `_MEIPASS` (`app.py:7-11,27`, `CRM_Local.spec`), Inno Setup (`CRM_Local.iss`), Windows autostart (`app.py:259-283`), loopback-only bind + free-port selection (`app.py:289-311`), CI test + Windows build workflows (`.github/workflows/ci.yml`, `windows-build.yml` — both run pytest).

---

## 2. CRM_Developer feature inventory (from actual source)

Stack: FastAPI + async SQLAlchemy/Supabase Postgres (`db/database.py`), routers under `api/`, services under `services/`, vanilla-JS SPA in `frontend/` (served by `main.py:152`), Supabase JWT auth on every router (`main.py:142-150`).

### 2.1 API surface (28 routes + `/health`)

| Route | Evidence | Capability |
|---|---|---|
| POST `/api/parse` | `api/parse.py:20` | upload xls/pdf (magic-byte check `api/parse.py:33-38`); xlsx handled in-browser |
| POST `/api/intake` | `api/intake.py:30` | universal 6-format multipart intake, 50-file/10MB/100MB caps, extraction run + provenance |
| GET `/api/jobs/{id}`, POST `/api/jobs/{id}/cancel` | `api/intake.py:170,176` | job status/cancel (also stubbed) |
| GET/PUT `/api/settings`, POST `/api/settings/test-llm` | `api/settings.py:47,52,86` | settings + **chain validation** (provider allow-list `api/settings.py:61`, model regex `:64`, base_url restricted to ollama `:66`, theme allow-list `:77`) |
| POST `/api/contacts/batch` | `api/contacts.py:121` | validated batch import → session row + dedup vs existing + company find-or-create (`api/contacts.py:79-103`) |
| PUT/DELETE `/api/contacts/{id}`, DELETE `/api/contacts` | `api/contacts.py:305,383,394` | edit / delete / bulk delete |
| POST/GET/PUT/DELETE `/api/calls*` | `api/calls.py:61,92,111,135` | call logs with date, duration, type, outcome, notes, next_action, next_action_date |
| POST `/api/eml/process` | `api/eml.py:219` | **separate** EML upload flow (not unified), LLM budget deadline, staging + auto-push |
| GET `/api/eml/contacts` (search/status/pushed/page) | `api/eml.py:372` | staged-contact listing = the closest thing to a Review Queue |
| GET `/api/eml/emails`, `/api/eml/emails/{id}` | `api/eml.py:385,392` | email browser backend (detail includes related contacts) |
| GET `/api/eml/contacts/export` | `api/eml.py:399` | CSV export with formula-injection sanitize (`api/eml.py:416-421`) |
| POST `/api/eml/contacts/{id}/push`, `/push-bulk` | `api/eml.py:482,500` | approve/stage → CRM, idempotent, bulk with partial-failure reporting |
| GET/DELETE `/api/history`, `/api/history/{id}`, GET `/…/export` | `api/history.py:130,139,154,160` | import sessions with mapping + per-record rows + call-log merge on export |
| POST `/api/export/pdf` | `api/export_pdf.py:25` | server-side PDF report (reportlab, `services/pdf_exporter.py:36`) |
| POST `/api/auth/upsert` | `api/auth.py:19` | Supabase identity (NOT to be migrated) |
| GET `/health` | `main.py:127` | DB ping, 503 on degraded |

### 2.2 Frontend views — 14 view containers (`frontend/index.html`), 12 nav entries (`:48-101`)

`upload` (149), `mapping` (187), `processing` (213), `dashboard` (225), `analytics` (249), `table` (255), `quality` (281), `dedup` (286), `eml-upload` (301), `customer-profiles` (320), `eml-contacts` (333), `eml-emails` (353), `eml-settings` (363), `history` (376). Sidebar also carries 5 export actions: Excel/CSV/PDF/VCF/ZIP (`index.html:89-101`).

Two JS files: `frontend/app.js` (2007 lines) + `frontend/eml.js` (459 lines).

### 2.3 Services

| Service | Evidence | Role |
|---|---|---|
| `services/extraction.py` (60) | `run_extraction` / `run_batch` | **the missing-in-target orchestrator**: adapter → local → optional LLM (deadline) → merge → field_origin |
| `services/data_access.py` (337) | `upsert_contact` `:102`, `list_contacts` `:83`, `find_or_create_company` `:42`, call-log/session/processed-file helpers | the C-01 data-access layer the target lacks |
| `services/eml_store.py` (92) | Supabase table wrappers | **cloud-specific — must be replaced by SQLite, not ported** |
| `services/llm_router.py` (176) | `PROVIDERS` `:31`, `extract_json` `:139`, `ChainEntry` `:14` | provider manager with deadline; 1 attempt/provider (`:158`) |
| `services/pdf_exporter.py` (208) | `generate_pdf` `:36` | reportlab PDF (new dependency for the target) |
| `services/adapters/` (6) | same registry shape as target | already ported |
| `services/eml_processor.py`, `eml_dedup_rules.py`, `parser.py` | **byte-identical to the target** (verified by `diff` this session) | shared, keep in sync |
| `core/auth.py`, `core/rate_limit.py` | Supabase JWT + slowapi | **not to be migrated** (loopback, single user) |

### 2.4 Database — 11 SQLAlchemy models (`db/models.py`): `users` (16), `companies` (28), `contacts` (45), `call_logs` (73), `session_data` (92), `records` (110), `processed_files` (120), `eml_emails` (131), `eml_contacts` (152), `extraction_runs` (179), `_migration_log` (194). Same shape as the target's schema.

### 2.5 Capability-by-capability (what the reference actually has)

| Capability | Present? | Evidence / reality check |
|---|---|---|
| Contacts (CRM table) | **partial** | written via `POST /contacts/batch`, edited/deleted individually; **there is NO `GET /api/contacts`** — `data_access.list_contacts` (`services/data_access.py:83`) exists but is unrouted; the Data Table view is entirely client-side over the current upload session (`frontend/app.js:1073 renderTable`, `S.clean`) |
| Companies | **partial** | `Company` model (`db/models.py:28`) created implicitly by find-or-create on batch import (`api/contacts.py:79`); **no companies view, no companies API, no merge** |
| Calls & Activities | **partial** | full CRUD API (`api/calls.py`) but only reachable from the contact edit panel (`frontend/app.js:1718 showContactPanel`, `:1794 addCallLogFromPanel`); **no standalone Activities view** |
| Notes | **partial** | `CallLog.notes` only (`db/models.py:82`); no entity-level notes |
| Follow-ups | **partial** | `next_action` / `next_action_date` on call logs (`api/calls.py:22-23`); **no due-today/upcoming/overdue views, no completion state** |
| Saved views | **absent** | no matches in `frontend/*.js` |
| Tags | **absent** | no tag model/column |
| Duplicates | **partial** | client-side `findDuplicates()` (`frontend/app.js:674`), "Keep First" (`:1020-1041`) on the *unsaved* session dataset — **no server-side merge, no field-level selection, no relationship preservation** |
| Data Quality | **partial** | client-side fill-rate + email/phone valid-invalid-missing over the current session (`frontend/app.js:963-1001`); **no categories, no per-record corrective actions, not persisted** |
| Processing History | **partial** | `GET /history` sessions with `total_records/imported/skipped/mapping` (`api/history.py:130-137`); **no duration, no errors, no updated/failed counts, no reprocess** |
| Exports | **present** | XLSX/CSV client-side (`frontend/app.js:1252,1258`), VCF (`:1847`), ZIP (`:1859`), PDF server-side (`api/export_pdf.py:25`); formula-injection guards on CSV (`api/eml.py:416`) and PDF filename (`api/export_pdf.py:33`) |
| Email browser | **present** | two-pane list + detail with related contacts (`api/eml.py:385,392`; `frontend/eml.js:271 loadEmails`); **emails preserved even with 0 contacts** (stored before extraction) |
| Dashboard | **partial** | KPIs computed from the **current upload session** (`frontend/app.js:760 buildKPIs`, `S.clean.length`), not from the database — the target's "every stat from real DB values" requirement is *stronger* than the reference |
| Import sessions / field mapping | **present** | mapping UI (`frontend/app.js:456 buildMapping`, `view-mapping` `index.html:187`), persisted in `session_data.mapping` (`api/contacts.py:136`); **no import templates/profiles** |
| Staged EML contacts | **present** | `eml_contacts` with `dedup_status` + `pushed_to_crm`, filters (search/status/pushed/paging), single + bulk push (`api/eml.py:372,482,500`) — but **auto-pushes by default** (`api/eml.py:319-331`), i.e. not a true Review-First queue |
| Settings | **partial** | provider chain validation + test (`api/settings.py`), but stored **in memory only** (`api/settings.py:16 _settings` dict — lost on restart) and API keys round-trip to the browser |
| Search | **partial** | per-view search boxes (`frontend/index.html:326,339`); **no global search** across contacts/companies/emails/addresses/files/activities |
| Command palette / keyboard shortcuts | **absent** | zero `keydown`/`ctrlKey`/`metaKey` matches in `frontend/*` |
| Accessibility | **partial** | skip link (`frontend/index.html:30`), a few `aria-label`s; no focus-visible/reduced-motion declarations found in `style.css` |
| Charts | **present (to be dropped)** | `addBarChart`/`addDonutChart` (`frontend/app.js:1112,1127`) + Chart.js CDN — **must not be ported** (brief bans charts and CDN deps) |
| Cloud-only (do not migrate) | — | Supabase auth (`core/auth.py`, `signin.html`), Postgres/asyncpg, slowapi proxy rate limits, CORS allow-list, Render/Vercel config, Google Fonts + 4 CDN scripts (`frontend/index.html:6-17`), separate EML Supabase project (`services/eml_store.py:14-25`) |

---

## 3. Parity matrix

Status legend: **present** = usable equivalent exists in the target; **partial** = exists but incomplete/incorrect relative to the brief; **missing** = nothing in the target.
"Reference" column = whether CRM_Developer itself has it (a `missing` there means net-new work, not a port).

### 3.1 Capability matrix

| # | Capability | In reference (path) | In target (path) | Status (target) | Adaptation note (cloud → local) |
|---|---|---|---|---|---|
| 1 | Dashboard KPIs from real DB values | partial — session-scoped KPIs `frontend/app.js:760` | partial — placeholders `static/app.js:50-66`, `db.counts()` `db.py:514` | **partial** | Must be rebuilt against SQLite aggregates (contacts, companies, valid email/phone, needs-review, staged pending, follow-ups due, failed jobs, recent activity). Reference offers no server KPI endpoint to port. |
| 2 | Dashboard actionable items / recent activity | missing | missing (`app.js:62` static text) | **missing** | Net-new; needs an activity source (processed_files + extraction_runs + call_logs + staged rows). |
| 3 | Import Center: universal 6-format dropzone | partial — `POST /api/intake` `api/intake.py:30` + separate EML flow `api/eml.py:219` | partial — `POST /api/intake` `app.py:136` + dropzone `static/index.html:55` | **partial** | Local has one dropzone for all 6 (good, keep); broken transport (bare filenames `app.js:114`); must **not** copy the reference's separate EML upload view. |
| 4 | Mixed-file queue, folder scanning | partial — no folder scan (cloud) | present — queue `app.js:69-99`, scan `pipeline.py:210`, watcher `pipeline.py:273` | **present** | Local-only advantage; keep. |
| 5 | Field mapping UI + preview + validation | present — `frontend/app.js:456`, `view-mapping` `index.html:187` | missing — silent auto-mapping `parse.py:45` only | **missing** | Port the mapping *concept* (client→server handoff must become a server-side session, see §4). |
| 6 | Import templates/profiles | missing | missing | **missing** | Net-new for both. |
| 7 | Import policy (Review First / Smart Import / Always Stage) | missing (auto-push `api/eml.py:319`) | missing (writes straight to `contacts` `intake.py:106`) | **missing** | Net-new; needs the staging table first. |
| 8 | Processing status + per-file results | partial — `api/intake.py` per-file results | partial — per-file results `intake.py:114-123`; jobs are stubs `app.py:148-157` | **partial** | Local must implement real job state or drop the stub endpoints. |
| 9 | Review Queue (staged contacts, tabs, filters) | partial — staged list with status/pushed filters `api/eml.py:372` | partial — `eml_contacts` table only (`db.py:132`), no API/UI | **partial** | Port filter/paging shape; tabs (All/Needs review/Ready/Dupes/Conflicts/Imported/Rejected/Failed) are net-new and require the 3-dimension status model. |
| 10 | Bulk approve/reject | partial — push/push-bulk `api/eml.py:482,500` | missing | **missing** | Adapt: "push" → "approve", add reject; must be local-transactional (single SQLite txn). |
| 11 | Duplicate comparison + conflict resolution UI | partial — "Keep First" `frontend/app.js:1020` (client-side only) | missing (`app.js:286` placeholder) | **missing** | Net-new server-side; needs field-level selection and relationship preservation (brief) — reference has neither. |
| 12 | Edit-before-approve / merge into existing / view original source | partial — edit modal `frontend/app.js:1570`, source file column | missing (edit = `prompt()` `app.js:185`) | **missing** | Port the edit-modal pattern; source preview needs `eml_emails.file_path` + raw row retention. |
| 13 | Contacts: server-side pagination + search | missing — no `GET /contacts` in reference | present — `app.py:175` + `db.list_contacts` `db.py:480` | **partial** | Local is *ahead*; still needs sort/filter params and an index-backed query plan for 10k+ rows. |
| 14 | Contacts: sorting, advanced filters, saved views, column management | missing (client-side sort `frontend/app.js:1097`, col filters `:1042`) | partial — sort UI is a no-op (`app.js:179`), filter control broken (`index.html:80`) | **missing** | Net-new server API (`sort`,`filter` params) + saved-views table. |
| 15 | Contacts: bulk operations, detail drawer, inline editing | partial — bulk delete `api/contacts.py:394`, modal edit `frontend/app.js:1570` | partial — single-row edit/delete only `app.py:186,200` | **partial** | Port the modal/drawer pattern; add bulk endpoints. |
| 16 | Contacts: related emails, provenance, call history, notes, follow-ups | partial — provenance `field_origin/extraction_run_id` (`api/eml.py:298-301`), calls panel `frontend/app.js:1718` | partial — provenance columns exist (`db.py:71-72`) but **unpopulated**; call_logs/notes/follow-ups unwritten | **partial** | Populate provenance in *both* intake paths; wire `call_logs` (schema already correct). |
| 17 | Companies directory, search, filters, associated contacts | partial — model + find-or-create `db/models.py:28`, `api/contacts.py:79`; **no view** | partial — table exists (`db.py:54`) but **never written**, no API/UI | **missing** | Net-new API + view; must start populating `companies` and `contacts.company_id` (currently free-text `company` only). |
| 18 | Company merge with review | missing | missing | **missing** | Net-new for both. |
| 19 | Emails two-pane browser (headers, body, extracted contacts, related records, source) | present — `api/eml.py:385,392`, `frontend/eml.js:271` | missing — placeholder `app.js:216` | **missing** | Port list/detail shape onto SQLite (`eml_emails` already has every column, `db.py:121-128`). |
| 20 | Emails preserved when extraction finds none | partial — emails stored before extraction | partial — `pipeline.py:149` stores email but **skips contact**; **intake path stores neither** | **partial** | Fix intake EML path to write `eml_emails` unconditionally (§4). |
| 21 | Calls & Activities (date/duration/direction/outcome/notes/next action/follow-up date) | partial — API `api/calls.py`, no view | missing — table only `db.py:84` | **missing** | Port `api/calls.py` shape 1:1 (fields already match); add the standalone view. |
| 22 | Chronological activity in contact/company profiles | partial — call logs in panel `frontend/app.js:1759` | missing | **missing** | Net-new query (union of call_logs, staged rows, processed files). |
| 23 | Duplicates workspace with field-level selection | missing (client-side group remove) | missing | **missing** | Net-new; must extend `db.DedupIndex` into a persisted candidate list. |
| 24 | Data Quality unified validator with 7 categories | missing (valid/invalid/missing only) | missing (regex over 1000 rows `app.js:275`) | **missing** | Net-new single `validation.py` engine; **delete** the client-side duplicate logic in `app.js` to avoid a second engine. |
| 25 | Processing History (file, type, session, counts, duration, errors, safe reprocess) | partial — sessions `api/history.py:130` (no duration/errors) | partial — `processed_files` table (`db.py:150`) has status/detail/contacts_found but **no API/UI** (`app.js:296` stub) | **partial** | Local already stores more (per-file status+detail); needs an endpoint, duration, and reprocess action. |
| 26 | Exports XLSX/CSV/PDF/VCF/ZIP, filtered/selected, formula-safe | present — `frontend/app.js:1252,1258,1847,1859`, `api/export_pdf.py:25` | partial — XLSX only, unfiltered `app.py:214`, sanitize `export.py:37-40` | **partial** | PDF needs `reportlab` (new dep + PyInstaller hidden import); VCF/ZIP need a local implementation (reference uses CDN JSZip — banned). |
| 27 | Global search (contacts, companies, emails, phones, addresses, files, activities) | missing | missing | **missing** | Net-new; SQLite FTS5 or indexed LIKE across tables. |
| 28 | Command palette Ctrl/Cmd+K | missing (no keydown anywhere) | missing | **missing** | Net-new; first `keydown` listener in the codebase. |
| 29 | Tags, entity notes | missing | missing | **missing** | Net-new tables + endpoints (see §4 decision D-8). |
| 30 | Follow-ups (due today / upcoming / overdue / completed) | partial — `next_action_date` only | partial — column exists `db.py:89`, never written | **missing** | Net-new queries over `call_logs.next_action_date` + a completion flag. |
| 31 | Undo / recovery | missing (only `confirm()` warnings) | missing | **missing** | Net-new where feasible (e.g. soft-delete or re-import). |
| 32 | Contextual help / shortcuts page | missing | missing (`docs/USER_GUIDE.md` is repo doc, not in-app) | **missing** | Net-new view; content can come from `docs/USER_GUIDE.md`. |
| 33 | Settings: single provider manager (7 providers, add/edit/remove/enable/reorder, model, base URL, key, test, timeout, retries) | partial — validation + test `api/settings.py:47-96`, in-memory store, no timeout/retry config | partial — chain CRUD `app.py:106-125`, test `app.py:253`, **fixed** timeout `llm.py:10` / retries `llm.py:9`, no reorder, no validation | **partial** | Merge into ONE settings surface (§4 decision D-3); add provider allow-list + model regex from `api/settings.py:61-66`. |
| 34 | Secrets never exposed to browser JS | missing (keys round-trip `api/settings.py`) | **missing — actively violated** `app.py:106-112`, `app.js:327-330` | **missing** | Local-specific fix: `GET` must return `api_key_set: bool`, never the key. |
| 35 | Extraction modes (local-only / AI enrichment) | partial — chain empty = local | present — `config.chain` `config.py:13`, `llm.extract` `llm.py:147` | **present** | Needs a UI switch + user-visible "AI will send data" indicator (brief). |
| 36 | ONE staging system / ONE canonical contacts DB | n/a | **conflict** — intake writes only `contacts`; pipeline writes `eml_contacts` + `contacts` | **conflict** | Must converge on staging-then-approve (§4). |
| 37 | ONE extraction orchestration system | present — `services/extraction.py` | **conflict** — `pipeline.py` and `intake.py` are two orchestrators; `services/extraction.py` does not exist | **conflict** | Port `run_extraction`/`run_batch` from the reference as the single orchestrator; make `pipeline.py` and `intake.py` thin callers. |
| 38 | ONE validation engine / ONE dedup engine | partial (dedup only, client-side) | **conflict** — `db.DedupIndex` vs `eml_dedup_rules.is_duplicate` vs per-adapter ad-hoc | **conflict** | Consolidate (§4). |
| 39 | ONE SQLite DB, no cloud, vanilla JS, no CDN, PyInstaller | n/a | **present** — `db.py:11`, `main.py`-equivalent binds loopback, `requirements.txt` pinned, no CDN refs in `static/` | **present** | Preserve; reference's CDN/auth/Postgres must not be copied. |
| 40 | Folder watch, ledger, native dialogs, Ollama, Inno Setup | missing in reference | **present** (`pipeline.py:273,523,297`, `llm.py:82`, `CRM_Local.iss`) | **present** | Preserve — these are local-only advantages. |
| 41 | WCAG 2.2 AA | partial (skip link `frontend/index.html:30`) | partial (focus-visible `style.css:121`, reduced-motion `:125`, aria-labels; **no skip link**) | **partial** | Add skip link + focus management; port nothing cloud-specific. |
| 42 | No charts anywhere | **violated** (Chart.js CDN `frontend/index.html:14`) | partial — text-only "Analytics" but chart-named ids `index.html:133-136` | **partial** | Delete/rename the Analytics view; never port `addBarChart`/`addDonutChart`. |

### 3.2 Navigation coverage (required 13 areas vs target)

| Required view | Target today | Evidence |
|---|---|---|
| Dashboard | partial (Overview, placeholder KPIs) | `index.html:38`, `app.js:50-66` |
| Import Center | partial (Extract, broken transport) | `index.html:55`, `app.js:114` |
| Review Queue | **missing** | — |
| Contacts | partial | `index.html:76` |
| Companies | **missing** | — |
| Emails | **missing** (stub) | `app.js:216` |
| Calls & Activities | **missing** | — |
| Duplicates | **missing** | `app.js:286` placeholder |
| Data Quality | partial | `index.html:141` |
| Processing History | **missing** (stub) | `app.js:296` |
| Reports & Exports | partial (one XLSX button) | `index.html:86`, `app.py:214` |
| Settings | partial (secrets exposed, no policies) | `index.html:168` |
| Help & Shortcuts | **missing** | — |

Views in the target that have **no place** in the required nav: `profiles` (`index.html:124`), `analytics` (`index.html:130`) — both must be folded into Contacts/Dashboard/Reports or removed.

### 3.3 Verdicts on the two prior audit docs

**Legend:** CONFIRMED = still true · STALE = understates committed work (now false) · WRONG = provably false.

`docs/LOCAL_PRODUCT_STATUS.md`:

| Claim (line) | Verdict | Evidence |
|---|---|---|
| "Universal extraction orchestrator `services/extraction.py` run_extraction(), run_batch()" (L29) | **WRONG** | file does not exist (`ls services/`) |
| "Universal intake endpoint MISSING" (L42, L65) | **STALE** | `app.py:136` |
| "Centralized settings API MISSING" (L43, L66) | **STALE** | `app.py:160,166` |
| "Job status/cancellation MISSING" (L44, L67) | **STALE** (but they are stubs) | `app.py:148-157` |
| "Adapter integration in pipeline MISSING" (L45) | **CONFIRMED** for `pipeline.py` (still `parse.py` path `pipeline.py:174-207`); **STALE** for intake (`intake.py:62-67` uses adapters) |
| "Provenance population in pipeline MISSING" (L46) | **CONFIRMED** | `intake.py:94-105` drops `source_row`/`field_origin`/`extraction_run_id`; no writer for `extraction_runs` |
| "14-view CRM workspace MISSING" (L68) | **STALE** | 9 views exist (`index.html:17-25`); still not the required 13 |
| "Hash-based routing MISSING" (L70) | **STALE** | `app.js:24,31-34,368-375` |
| "Rate limiting MISSING" (L48) | **CONFIRMED** | no limiter in target |
| "Unified 11-table schema ✅" (L14) | **CONFIRMED** | `db.py:52-168` (11 tables), single `crm.db` `db.py:11` |
| "FK enforcement ✅" (L15) | **CONFIRMED** | `db.py:23` |
| "Shared services byte-identical ✅" (L18) | **CONFIRMED** (verified by `diff` this session: `eml_processor.py`, `eml_dedup_rules.py`, `parser.py` all identical) |
| "Prompt injection wrapping ✅" (L19) | **CONFIRMED** | `services/eml_processor.py:265-272`, `llm.py:16` |
| "LLM output validation ✅" / "Gemini model validation ✅" (L22-23) | **CONFIRMED** | `llm.py:47-73`, `llm.py:94-97` |
| "Formula injection sanitization ✅" (L24) | **CONFIRMED for XLSX** | `export.py:37-40` (no CSV export exists yet) |
| "Security headers ✅" / "openapi_url=None ✅" (L25-26) | **CONFIRMED** | `app.py:32-38`, `app.py:30` |
| "6 extraction adapters ✅" (L27) | **CONFIRMED** | `services/adapters/` |
| "Folder watching / ledger / native dialogs / Ollama / PyInstaller / Autostart ✅" (L30-36) | **CONFIRMED** | `pipeline.py:273,523,297`, `llm.py:82`, `app.py:7-11`, `app.py:263` |
| "Test coverage ≥80% MISSING" (L71) / "22 tests" (L84) | **CONFIRMED** (gap) / **STALE** (count) | 58 tests now, no coverage gate in CI |
| "47 eml_contacts + 60 emails migrated" (L16) | **UNVERIFIABLE** from source (runtime claim) |

`docs/IMPLEMENTATION_REPOSITORY_AUDIT.md`:

| Claim (section) | Verdict | Evidence |
|---|---|---|
| "Two SQLite files (crm.db + eml.db)" (§1) | **STALE** | unified `crm.db` `db.py:11` (`eml.db` remains only as a migration source `db.py:216`) |
| "3 views (Run/Contacts/Settings), 570-line app.js" (§1) | **WRONG** | 9 views `index.html:17-25`; `app.js` is 374 lines |
| "CRM_Local has 0 modifications / NO implementation changes" (§8, §10) | **STALE** | HEAD `7610095` committed the whole audit's target work (2445 insertions) |
| "Unified 11-table schema ❌ 2 separate DBs" (§2) | **STALE** | `db.py:52-168` |
| "FK enforcement ❌ Not enabled" (§2) | **STALE** | `db.py:23` |
| "Prompt injection wrapping ❌ No wrapping" (§2) | **WRONG** | `services/eml_processor.py:265-272` |
| "Gemini model validation ❌ Not present" (§2) | **STALE** | `llm.py:94-97` |
| "merge_fields local-wins ❌ AI may overwrite" (§2) | **WRONG** | `merge_fields` local-wins in shared `eml_processor.py` (byte-identical to reference) + test `tests/test_pipeline.py:83` |
| "CSV formula injection ❌ Not sanitized" (§2) | **STALE for XLSX** (`export.py:37-40`); **CONFIRMED** in the sense that no CSV export exists to sanitize |
| "Magic bytes validation ❌ Not present" (§2) | **STALE** | `intake.py:19-22,54-59` |
| "openapi_url=None ❌" (§2) | **STALE** | `app.py:30` |
| "Security headers ❌ Not present" (§2) | **STALE** | `app.py:32-38` |
| "Log redaction ❌ Not present" (§2) | **CONFIRMED** | only `llm._redact` for provider errors (`llm.py:142`); no request/DB log redaction layer |
| "Extraction adapters (6) ❌ Monolithic parser" (§2) | **STALE** | `services/adapters/` (6 adapters + registry) |
| "NormalizedContact/ExtractionResult ❌" (§2) | **STALE** | `services/adapters/__init__.py:12,36` |
| "Universal intake ❌ Separate scan endpoints" (§2) | **STALE** | `app.py:136` |
| "Settings API ❌ Config via /api/config" (§2) | **STALE** | `app.py:160,166` (both exist — which is itself a finding) |
| "Provenance tracking ❌ Not present" (§2) | **STALE** (columns exist `db.py:71-72`) but **CONFIRMED** as unpopulated |
| "Adapter tests ❌ 5 test files" (§2) | **STALE** | 10 test files / 58 tests incl. 16 adapter tests |
| "Prompt injection tests ❌ Not present" (§2) | **CONFIRMED** | no injection test in `tests/` |
| "CI workflow PARTIAL — add test stage" (§2) | **STALE** | `ci.yml` and `windows-build.yml` both run `pytest tests/ -q` |
| "Dependency pinning ❌ Unpinned (fastapi==0.111.0 etc.)" (§2) | **WRONG** (self-contradictory) | `requirements.txt` pins fastapi/uvicorn/httpx/openpyxl/xlrd/PyMuPDF |
| "Accessibility ❌ Basic" / "Hash routing ❌" (§2) | **STALE** | focus-visible `style.css:121`, reduced-motion `:125`, aria-labels `index.html:14,16,30`, hash routing `app.js:24,31-34` (still short of the reference's skip link) |
| "Data access layer (C-01) ❌ Routers own ORM" (§2) | **CONFIRMED** | no `services/data_access.py` in target |
| "Health check PARTIAL — add /health" (§2) | **CONFIRMED** (nice-to-have) | only `/api/status` `app.py:90` |
| "Phone normalization VERIFY — may need update" (§2) | **CONFIRMED fixed** | `db.py:304-311`, `eml_dedup_rules.py:36-47` |

---

## 4. Placement map (who owns what, under the one-of-everything rule)

Principle: **one owner per concern**; existing files are extended rather than duplicated. `app.py` is already 315 lines with 18 routes; adding ~40 more routes there will not stay maintainable or PyInstaller-friendly without a split.

| # | Capability | Owning file/module (proposed) | Conflict / decision needed |
|---|---|---|---|
| P-1 | **Single extraction orchestrator** | new `services/extraction.py` (port `run_extraction`/`run_batch` from `CRM_Developer/services/extraction.py`) | **Conflict:** `pipeline.py` and `intake.py` both orchestrate today with divergent mapping/dedup. Both must become thin callers. Decide whether `parse.map_headers` or the adapters own header mapping (recommend: adapters call `parse.map_headers`, deleting the 4 duplicated naive mappers). |
| P-2 | **Staging system (Review Queue backend)** | new `staging.py` (or `services/staging.py`) + new table(s) in `db.py` schema/migration | **Conflict:** intake writes straight to `contacts` (`intake.py:106`) and pipeline writes `eml_contacts` + auto-push (`pipeline.py:164-171`). The brief's 3 status dimensions need a new `staged_contacts` table (or a widened `eml_contacts`); `eml_contacts` today only has `dedup_status` + `pushed_to_crm` (`db.py:137`). Decide: widen `eml_contacts` vs new table (the database-engineer's `docs/STAGED_CONTACT_ARCHITECTURE.md` owns this answer). |
| P-3 | **Routing / view architecture** | `static/index.html` + a new `static/js/` module tree (router, views) | **Conflict:** current UI is one 374-line non-module script driven by inline `onclick=` globals (`index.html:17-25`), which is incompatible with the brief's *native ES modules* requirement (inline handlers can't see module scope). Decision: keep hash routing (`app.js:24`) but move to `type="module"` + event delegation; 13 views ⇒ one module per view area, not one 2000-line file. |
| P-4 | **Settings / provider manager** | keep ONE endpoint family in `app.py` (or new `settings.py` router) + `config.py` as the only store | **Conflict:** `/api/config` and `/api/settings` both read/write `config.json` (`app.py:106-125` vs `160-172`). Recommend: `/api/settings` canonical, `/api/config` removed or made an alias; **both must stop returning `api_key`** (`app.py:106-112`). Add provider allow-list + model regex + base_url rule from `api/settings.py:61-66`; add timeout/retry per entry (today they are module constants `llm.py:9-10`). |
| P-5 | **Validation engine (Data Quality)** | new `validation.py` (single engine) writing a `validation_issues` table | **Conflict:** duplicate client-side logic in `static/app.js:275-290` must be deleted, not complemented, else two engines. The 7 categories are net-new (reference only has valid/invalid/missing). |
| P-6 | **Dedup engine** | extend `db.DedupIndex` (`db.py:345`) into the one engine; keep `eml_dedup_rules.py` as its pure-function core (already shared byte-identical) | **Conflict:** `intake.py:9` imports `is_duplicate` but never calls it; `pipeline.py` uses `DedupIndex`. One call site must win. Merge/duplicates workspace reads its output. |
| P-7 | **Contacts API** | extend `app.py` routes + `db.list_contacts` (`db.py:480`) | Needs `sort`, structured `filter`, and cursor/offset strategy proven at 10k+ rows; the current `ORDER BY id DESC` + `LIKE '%q%'` (`db.py:484-493`) will not serve advanced filtering. Decide on FTS5 vs indexed LIKE (affects P-9 too). |
| P-8 | **Companies** | new `/api/companies` routes + populate `contacts.company_id` | **Conflict:** `upsert_contact` (`db.py:409`) writes free-text `company` only; nothing ever inserts `companies`. Decide whether company creation happens at intake (upsert) or at review-approve time — recommend intake-time upsert keyed by normalized name (port `api/contacts.py:79-103`). |
| P-9 | **Global search + command palette** | new `search.py` route (`/api/search`) + `static/js/palette.js` (first `keydown` listener) | Depends on P-7 schema decisions; must search contacts, companies, emails, phones, addresses, source files, activities. |
| P-10 | **Emails browser** | new `/api/emails` routes over `eml_emails` (`db.py:121`) + `static/js/views/emails.js` | **Conflict:** intake never writes `eml_emails` (`intake.py:93-120`). Decide: route dropzone EML through the same EML store path as folder scan (recommended) so both sources produce email rows. |
| P-11 | **Calls & Activities** | new `/api/calls` routes (port `api/calls.py` shape) + view module; table already correct (`db.py:84`) | Decide follow-up completion semantics: add a `status` column to `call_logs` vs a separate `follow_ups` table (recommend: column + index on `next_action_date`). |
| P-12 | **Processing History** | new `/api/history` route over `processed_files` (`db.py:150`) + optionally `extraction_runs` (`db.py:155`) | Decide whether to start writing `extraction_runs` (currently dead) to carry duration/errors; safe reprocess = delete ledger row + requeue (`db.py:523-536`). |
| P-13 | **Reports & Exports** | extend `export.py` (owner of all export formats) | **Conflict:** PDF requires `reportlab` (reference `services/pdf_exporter.py`); VCF/ZIP in the reference are built with CDN JSZip (`frontend/index.html:15`) which is banned. Decide: add `reportlab` to `requirements.txt` + `CRM_Local.spec` hiddenimports, and write VCF natively (~50 lines) with a stdlib `zipfile` ZIP. |
| P-14 | **Jobs / long-running intake** | replace the stubs at `app.py:148-157` with real state (in-memory `RunState`-style like `pipeline.py:23`, or ledger-backed) | Decide: real async jobs vs delete the endpoints. The brief requires processing status; the current stubs return `done` unconditionally. |
| P-15 | **Dashboard aggregation** | new `stats.py` (or extend `db.counts()`) returning every KPI from SQL | **Conflict:** `static/app.js:56-61` currently fabricates Files/New/Duplicates/Completeness. All six KPIs + recent activity + actionable items must come from one endpoint; delete the client-side math. |
| P-16 | **Help & Shortcuts** | static view + content derived from `docs/USER_GUIDE.md` | No backend needed. |
| P-17 | **Undo/recovery** | where feasible: soft-delete flag on `contacts`/`staged_contacts`, or "revert last import session" using `processed_files`/`session_data` | Decide scope early — it shapes schema (hard delete today at `db.py:509`). |
| P-18 | **Tags / notes** | new tables + endpoints | Not in reference; decide table design before Phase 3 (P-2 staging schema should预留 the linkage). |
| P-19 | **Dead-code/schema cleanup** | `db.py` (triple `connect` at `:18/:295/:330`, dead aliases `:291-292`), unused tables (`users`, `session_data`, `records`) | Decide: keep `session_data`/`records` for import sessions (recommended — the reference's import-session model maps exactly onto them) vs delete. `users` has no purpose locally but is harmless. |
| P-20 | **Packaging** | `CRM_Local.spec`, `requirements.txt`, `.github/workflows/*` | Any new dependency (reportlab, python-multipart if uploads are adopted) needs `hiddenimports` + CI verification; PyInstaller `datas=[("static","static")]` (`CRM_Local.spec:7`) already bundles nested static dirs. |

---

## 5. Open questions for the orchestrator

1. **Intake transport:** the dropzone sends bare file names (`static/app.js:114`) which fail `os.path.exists` (`intake.py:40`) — real drag-and-drop is currently broken. Do we (a) switch to multipart upload (`UploadFile`, as the reference does in `api/intake.py:33`), or (b) keep server-side paths and make the UI pick files via native dialogs/folder scan only? This decides whether `python-multipart` becomes a new dependency.
2. **Staging table:** widen `eml_contacts` (already has `dedup_status`/`pushed_to_crm`/`crm_contact_id`) or create a new `staged_contacts` table for all 6 formats with the 3 status dimensions? (Coordinate with `docs/STAGED_CONTACT_ARCHITECTURE.md`.)
3. **Router split:** keep all routes in `app.py`, or introduce an `api/` router package (mirroring the reference) — and if split, who updates `CRM_Local.spec` hiddenimports and the CI test command?
4. **Config surface:** retire `/api/config` in favour of `/api/settings`, or keep both with `/api/config` returning secret-sanitized output? (Both currently write `config.json`.)
5. **Default import policy:** Review First vs Smart Import vs Always Stage — PRODUCT.md defers this to Phase 2; the staging schema and the dropzone's default button depend on it.
6. **EML convergence:** should dropzone-imported EML write `eml_emails` + stage into the review queue (like folder scan), instead of upserting directly into `contacts` as it does today (`intake.py:106`)?
7. **Companies ownership:** does `upsert_contact` create/link `companies` rows at extraction time, or only at approve time in the Review Queue? (Nothing writes `companies` today.)
8. **New dependencies:** approve `reportlab` (PDF export) and decide VCF/ZIP implementation (native vs vendored JSZip — CDN is banned). Both affect `requirements.txt` and `CRM_Local.spec`.
9. **Analytics view:** delete it (its ids are `chart-*` and the brief bans charts) or fold its text summaries into Dashboard/Reports & Exports?
10. **Undo scope:** hard-delete stays (as today, `db.py:509`) with undo only for imports, or soft-delete across contacts/staging? This must be decided before the staging schema is frozen.

---

*End of `docs/CRM_FEATURE_PARITY.md`.*
