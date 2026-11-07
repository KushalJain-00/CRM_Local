# Staged Contact Architecture — CRM_Local (SQLite)

**Status:** READ-ONLY investigation + target design. No code, schema, or data was modified.
**Date:** 2026-11-07 · **Target commit:** `7610095` ("unified database…") · **Target DB engine:** SQLite
**Evidence base:** `db.py` (root), `config.py`, `pipeline.py`, `intake.py`, `parse.py`, `app.py`, `services/*`, live DB files opened read-only (`sqlite3 -readonly`), reference repo `CRM_Developer/db/models.py` + its dev `crm.db`.

---

## 1. Current schema (verified)

### 1.1 Where the database lives

| Item | Evidence |
|---|---|
| Data directory: `~/.crm_local/` on Linux, `%APPDATA%\CRM_Local` on Windows | `config.py:21-27` |
| DB path resolves to `<data_dir>/crm.db` (legacy `<data_dir>/eml.db` still resolvable) | `config.py:34-37` |
| Live files found (read-only, 2026-11-07): `crm.db` 339,968 B, `eml.db` 184,320 B, `crm.db.bak` 45,056 B, `eml.db.bak` 184,320 B, `config.json` | `ls -la ~/.crm_local/` |
| Single connection path: WAL + `PRAGMA foreign_keys=ON` | `db.py:18-24` (defined three times — `db.py:18`, `db.py:295`, `db.py:330`; last definition wins, all identical) |
| `_UNIFIED_DB = "crm.db"` constant is dead (connect uses `config.db_path`) | `db.py:11` vs `db.py:20` |
| `PRAGMA integrity_check` = `ok`, `PRAGMA foreign_key_check` = empty | read-only run on `crm.db` |

**`eml.db` still exists on disk with a full copy of the EML data** (60 emails, 47 eml_contacts, 60 processed_files — identical counts to `crm.db`). The migration guard (`db.py:223-228`) skips re-copy when `crm.db.eml_emails` is non-empty, so `eml.db` is now a redundant legacy twin, not a live store. `config.db_path("eml")` is still referenced by `_migrate_eml_data` (`db.py:219`) and exposed by `/api/config` (`app.py:111`).

### 1.2 Tables in `crm.db` (source: `_SCHEMA_UNIFIED`, `db.py:52-168`; verified against live `sqlite_master`)

Live row counts (2026-11-07, read-only):

| Table | DDL lines | Columns (type) | PK / FK | Indexes | Rows |
|---|---|---|---|---|---|
| `companies` | `db.py:54-61` | id, name, address, city, pincode, website, industry, product, created_at, updated_at (all TEXT except id) | PK id; **no FK** | `idx_companies_name`, `idx_companies_city` | **0** |
| `contacts` | `db.py:63-82` | id, company_id INTEGER, name, email_primary, email_secondary, phone_primary, phone_secondary, phone_country DEFAULT 'IN', company, designation, address, city, pincode, website, whatsapp, position, files, products_misc, source_file, source_row INTEGER, extraction_run_id INTEGER, field_origin, email_key, phone_key, created_at, updated_at | PK id; DDL declares `company_id REFERENCES companies(id) ON DELETE SET NULL` (`db.py:65`) — **but see FK drift note below** | `idx_contacts_company_id/name/email_primary/email_secondary/phone_primary/phone_secondary/email_key/phone_key` (`db.py:75-82`) | 55 |
| `call_logs` | `db.py:84-94` | id, contact_id, company_id, call_date, duration_minutes INTEGER, call_type, outcome, notes, next_action, next_action_date, created_by, created_at | PK id; FK contact_id→contacts CASCADE, company_id→companies SET NULL (`db.py:86-87`) | `idx_call_logs_contact_id/company_id/call_date` | **0** |
| `users` | `db.py:96-102` | id, email UNIQUE NOT NULL, name, provider_uid, last_login, created_at | PK id | `idx_users_email`, `idx_users_provider_uid` | **0** |
| `session_data` | `db.py:104-111` | id, file_name, sheet_name, upload_date, mapping, user_id, total_records DEFAULT 0, imported DEFAULT 0, skipped DEFAULT 0, is_active DEFAULT 1, created_at | PK id; FK user_id→users CASCADE | `idx_session_data_user_id` | **0** |
| `records` | `db.py:113-118` | id, session_id, data (raw JSON row), created_at | PK id; FK session_id→session_data CASCADE | `idx_records_session_id` | **0** |
| `eml_emails` | `db.py:121-130` | id, file_name, file_path, subject, date, sender_name, sender_email, **to_emails, cc_emails, bcc_emails**, body_text, has_signature INTEGER, signature_block, processed_at, created_at | PK id; **no FK** | `idx_eml_emails_sender_email`, `idx_eml_emails_date` | 60 |
| `eml_contacts` | `db.py:132-147` | id, source_email_id, name, email, phone_primary, phone_secondary, company, designation, address, city, pincode, website, dedup_status, pushed_to_crm DEFAULT 0, crm_contact_id, source_file, to_emails, cc_emails, bcc_emails, field_origin, email_key, phone_key, created_at, updated_at | PK id; FK source_email_id→eml_emails CASCADE, crm_contact_id→contacts SET NULL (`db.py:134,138`) — both confirmed live via `PRAGMA foreign_key_list` | `idx_eml_contacts_source_email_id/crm_contact_id/email/email_key/phone_key` (`db.py:143-147`) | 47 |
| `processed_files` | `db.py:150-153` | path PK, size, mtime REAL, status, detail, contacts_found, processed_at | PK path | sqlite autoindex | 62 |
| `extraction_runs` | `db.py:155-162` | id, user_id, started_at, completed_at, status DEFAULT 'running', files_processed, contacts_found, error, config_snapshot | PK id; FK user_id→users SET NULL | `idx_extraction_runs_user_id` | **0** |
| `_migration_log` | `db.py:164-167` | version PK, name NOT NULL, applied_at NOT NULL, rollback_sql, checksum | PK version | — | 1 (`version=1, name=unified_schema, 2026-11-06 14:14:55`) |

**No CHECK constraints exist anywhere** (live `sqlite_master` inspection): no status enums, no NOT NULL beyond users.email.

**FK drift (verified):** in the *live* `crm.db`, `PRAGMA foreign_key_list(contacts)` returns **empty** — `contacts.company_id` has **no FK**, because the live table pre-dates unification and `company_id` was appended by `_ensure_columns`'s `ALTER TABLE … ADD COLUMN` (`db.py:31-37`, `db.py:211`), which cannot add a FOREIGN KEY in SQLite. The DDL at `db.py:65` only provides the FK for *freshly created* databases. A fresh install and the user's current DB therefore have different schemas for `contacts`. `eml_contacts` was created by the unified DDL, so its two FKs are live.

### 1.3 Does the claimed eml→unified migration code exist, and what does it actually do?

Yes: `_migrate_eml_data()` at `db.py:216-287`, invoked from `init()` → `_migrate()` (`db.py:47`, `db.py:193`).

What it does:
1. Guard: if `eml_emails` already has rows, return — migration considered done (`db.py:223-228`).
2. Copies `eml.db:emails` → `crm.db:eml_emails` (`db.py:234-249`); maps old columns by name; **does not copy `signature_block`** (old `emails` table has none) and **`eml_emails` has no `receiver_name`/`receiver_email` columns to receive them**.
3. Copies `eml.db:eml_contacts` → `crm.db:eml_contacts` (`db.py:251-268`); old `email_id`→`source_email_id`, `email_primary`→`email`, `pushed`→`pushed_to_crm`, **forces `dedup_status='NEW'`** (`db.py:264`), drops old `email_secondary`/`phone_secondary`/`status` columns.
4. Merges `eml.db:processed_files` with `INSERT OR IGNORE` (`db.py:270-282`).
5. **Every exception is swallowed with `pass`** (`db.py:248-249, 267-268, 286-287`) — a partial migration reports success. Row counts are never verified; no entry with `rollback_sql`/`checksum` is written (`db.py:197` writes only version/name/date).

Verified result: 60 emails + 47 eml_contacts copied; **`eml.db` left in place with the same 47/60 rows (duplicate)**; `crm.db._migration_log` has exactly one row.

### 1.4 What writes what (code paths)

| Writer | Target | Evidence |
|---|---|---|
| Folder scan → docs (xlsx/xls/csv/pdf) | `contacts` directly (no staging) | `pipeline.py:174-207`, `upsert_contact` call `pipeline.py:200` |
| Folder scan → eml | `eml_emails` + `eml_contacts` + `contacts` (dual write) | `pipeline.py:149, 156-161, 164-171` |
| Universal intake (6 formats incl. EML) | `contacts` directly — **no `eml_emails` row, no `session_data`/`records`, no staging** | `intake.py:92-112`, `intake.py:106` |
| EML adapter | returns 1 NormalizedContact per email; email row never stored on this path | `services/adapters/eml.py:39`, `intake.py:67` |
| `_ensure_columns` | additive ALTERs | `db.py:202-213` |
| Anything inserting `companies`, `call_logs`, `users`, `session_data`, `records`, `extraction_runs` | **NO WRITER EXISTS** (repo-wide grep: zero `INSERT INTO` for these tables) | grep over `*.py` |
| Anything populating `source_row`, `field_origin`, `extraction_run_id`, `whatsapp`, `position`, `files`, `products_misc`, `company_id` | **never persisted** — adapters build them (`services/adapters/__init__.py:30-32`, `intake.py:90`) but `upsert_contact`'s column list omits them (`db.py:434-439`) | verified: 0 non-null rows in live DB for all of these; `designation` 31/55 non-null, `position` 0/55 |

**EML emails discarded for lack of a contact (spec violation):** `pipeline.py:145-147` returns *before* `insert_email` (`pipeline.py:149`) when a mail has no email/phone. The intake path stores no email row at all. Spec §3: "emails are NEVER discarded for lack of a contact".

**Email↔contact cardinality today:** `eml_contacts.source_email_id` is technically 1:N from the email side, but the pipeline creates ≤1 contact per email (`pipeline.py:161`; `services/adapters/eml.py:39` returns exactly one). Contact→emails has **no FK at all** — only the free-text `contacts.source_file`, filled once and never overwritten (`db.py:431`). So neither direction of the required M:N is modeled or populated (`eml_contacts.crm_contact_id` is NULL in **47/47** rows despite `pushed_to_crm=1` in 47/47).

### 1.5 Prior-doc claims vs reality (docs are stale — verified)

| Claim | Where | Verdict |
|---|---|---|
| "Universal intake endpoint … MISSING" | `docs/LOCAL_PRODUCT_STATUS.md:42` | **STALE** — `POST /api/intake` exists (`app.py:136-146`) |
| "Universal extraction orchestrator `services/extraction.py` run_extraction(), run_batch()" | `docs/LOCAL_PRODUCT_STATUS.md:29` | **FALSE — file does not exist** (`ls services/`: only `adapters/`, `eml_dedup_rules.py`, `eml_processor.py`, `parser.py`) |
| "Adapter integration in pipeline … MISSING" | `docs/LOCAL_PRODUCT_STATUS.md:45` | still true — `pipeline.py` uses `parse.read_table`, only `intake.py` uses adapters |
| "Provenance population in pipeline … MISSING" | `docs/LOCAL_PRODUCT_STATUS.md:46` | still true (0 rows populated) |
| "47 eml_contacts + 60 emails + 62 processed_files migrated" | `docs/LOCAL_PRODUCT_STATUS.md:16` | 47/60 correct; 62 = 60 migrated + 2 pre-existing (eml.db has 60) — imprecise |
| "Shared services byte-identical with CRM_Developer" | `docs/LOCAL_PRODUCT_STATUS.md:18` | **VERIFIED TRUE** (`diff` = identical for `eml_processor.py`, `eml_dedup_rules.py`, `parser.py`) |
| "Two SQLite files (crm.db + eml.db)" / "❌ 2 separate DBs" | `docs/IMPLEMENTATION_REPOSITORY_AUDIT.md:15,25` | **STALE** — one live DB (`crm.db`); `eml.db` is a leftover duplicate |
| "Merge … into single crm_local.db" | `docs/IMPLEMENTATION_REPOSITORY_AUDIT.md:76` | actual name is `crm.db` |
| "The 11-table schema is in CRM_Developer, not CRM_Local" | `docs/IMPLEMENTATION_REPOSITORY_AUDIT.md:191` | **STALE** — CRM_Local has 11 tables (incl. `_migration_log`) |
| "All 11 tables created" | `docs/LOCAL_PRODUCT_STATUS.md:14` | true count-wise, but 6 of them have **zero rows and no writer code** |

---

## 2. Reference schema (CRM_Developer)

Source: `CRM_Developer/db/models.py` (SQLAlchemy, 11 models, lines cited) + its dev `crm.db` (read-only).

| Model / table | Lines | Notes | Mapping to CRM_Local target |
|---|---|---|---|
| `User` (`users`) | `models.py:16-25` | email UNIQUE, name, provider_uid, last_login | → `crm.db.users` (exists, unused; local single-user — keep for compat only) |
| `Company` (`companies`) | `models.py:28-42` | name/address/city/pincode/website/industry/product + timestamps; relationships → contacts, call_logs | → `crm.db.companies` (exists, **never written**) |
| `Contact` (`contacts`) | `models.py:45-70` | includes `position`, `whatsapp`, `files`, `products_misc`, `source_file`, `source_row`, `extraction_run_id` **FK→extraction_runs**, `field_origin` (JSON), `email_key`, `phone_key` | → `crm.db.contacts` — same column set, but `extraction_run_id` has **no FK** in CRM_Local DDL (`db.py:71`) and nothing populates it |
| `CallLog` (`call_logs`) | `models.py:73-89` | all spec §3 call fields | → `crm.db.call_logs` (exists, unused) |
| `SessionData` (`session_data`) | `models.py:92-107` | file_name, sheet_name, upload_date, mapping JSON, user_id, counters, is_active | → `crm.db.session_data` (exists, unused) |
| `Record` (`records`) | `models.py:110-117` | session_id, data JSON, created_at — raw row retention | → `crm.db.records` (exists, **unused — mandatory raw retention not implemented**) |
| `ProcessedFile` | `models.py:120-128` | path PK | → `crm.db.processed_files` (used by pipeline only) |
| `EmlEmail` (`eml_emails`) | `models.py:131-149` | has **`receiver_name`, `receiver_email`** (139-140) and `signature_block` | CRM_Local **lacks `receiver_name`/`receiver_email`** columns; `signature_block` exists but is never written |
| `EmlContact` (`eml_contacts`) | `models.py:152-176` | staged EML contact: dedup_status, pushed_to_crm, crm_contact_id, to/cc/bcc | → `crm.db.eml_contacts` (47 rows; `crm_contact_id` never set) |
| `ExtractionRun` | `models.py:179-192` | run ledger with config_snapshot | → `crm.db.extraction_runs` (exists, unused) |
| `MigrationLog` | `models.py:194-200` | version PK, rollback_sql, checksum | → `crm.db._migration_log` (1 row, no rollback_sql/checksum recorded) |
| `eml_jobs`, `eml_job_files` | **not in models.py**; present only in dev `crm.db` | orphaned (confirmed by CRM_Developer's own handoff `.opencode/team/handoffs/HANDOFF-BE-audit.md:121`) | **Do not port** — no model, no code, 0 rows |
| EML staging in dev DB | dev `crm.db` has separate `eml_contacts` (same shape) | CRM_Developer's "staging" is EML-only (`MASTER_PROMPT.md:100-103`: `/api/eml/contacts` push endpoints) | **Not a unified staging model** — target must build `staged_contacts` for all six formats |

CRM_Developer's proposed consolidated schema doc `CRM_Developer/docs/DATABASE_SCHEMA.md` (Phase 1, status "Proposed") matches the 11 tables above; it contains **no unified staging table either** — the unified six-format staging model is new ground for both repos.

The 25 field-mapping types live in the CRM_Developer frontend (`frontend/app.js:21-46`, `FT` object; listed at `CRM_Developer/CONTEXT.md:452`): company, contact, phone, email, address, city, pincode, website, product, industry, amount, date, status, id, keyword, location, facebook, member, fax, whatsapp, files, stdcode, landline, other, skip.

---

## 3. Gap analysis (spec §3/§4 × current schema)

Legend: **present** = column exists and is used · **present-unpopulated** = column exists, zero rows written · **missing** = no column · **misplaced** = data lives in the wrong column/table · **no-writer** = table/column exists, no code path writes it.

### 3.1 Company (spec §3)

| Spec field | Current table.column | Status |
|---|---|---|
| id | `companies.id` (`db.py:55`) | present (but table empty) |
| name | `companies.name` (`db.py:56`) | present-unpopulated (0 rows; **company names live in `contacts.company`** — misplaced) |
| address | `companies.address` (`db.py:56`) | present-unpopulated |
| city | `companies.city` (`db.py:56`) | present-unpopulated |
| pincode | `companies.pincode` (`db.py:56`) | present-unpopulated |
| website | `companies.website` (`db.py:56`) | present-unpopulated |
| industry | `companies.industry` (`db.py:57`) | present-unpopulated — no code ever sets industry (adapters have no industry field) |
| product | `companies.product` (`db.py:57`) | present-unpopulated; `contacts.products_misc` exists (`db.py:70`) but also 0 rows — **both sides unused** |
| created_at | `companies.created_at` (`db.py:58`) | present-unpopulated |
| updated_at | `companies.updated_at` (`db.py:58`) | present-unpopulated |
| Company ≠ contact info (designation ≠ industry; product description ≠ company name) | enforced nowhere: `upsert_contact` writes `company` as free text (`db.py:434-438`); no company resolution step exists | **missing** (no resolver) |

### 3.2 Canonical contact (spec §3)

| Spec field | Current table.column | Status |
|---|---|---|
| id | `contacts.id` | present |
| name | `contacts.name` (`db.py:66`) | present |
| company_id (resolved by app, never LLM) | `contacts.company_id` (`db.py:65`) | **present-unpopulated + no FK in live DB** (§1.2); zero resolution code |
| email_primary | `contacts.email_primary` (`db.py:66`) | present |
| email_secondary | `contacts.email_secondary` (`db.py:67`) | present (populated via alias path `db.py:420`) |
| phone_primary | `contacts.phone_primary` (`db.py:67`) | present |
| phone_secondary | `contacts.phone_secondary` (`db.py:67`) | present |
| phone_country | `contacts.phone_country` DEFAULT 'IN' (`db.py:68`) | present-unpopulated (never written by upsert) |
| whatsapp (evidence only) | `contacts.whatsapp` (`db.py:70`) | present-unpopulated (0 rows; parser maps "whatsapp" headers to phone_primary — `parse.py:28`) |
| position | `contacts.position` (`db.py:70`) | present-unpopulated — writers use legacy `designation` instead (31/55 rows) — **misplaced** |
| city | `contacts.city` (`db.py:69`) | present |
| address | `contacts.address` (`db.py:69`) | present |
| pincode | `contacts.pincode` (`db.py:69`) | present |
| files | `contacts.files` (`db.py:70`) | present-unpopulated |
| created_at / updated_at | `contacts.created_at/updated_at` (`db.py:73`) | present; `updated_at` never refreshed on enrich (`db.py:419-424` doesn't set it) |
| alias `designation`→`position` | both columns exist; code reads/writes `designation` (`db.py:419-420, 436`) | **misplaced** — alias not applied |
| alias EML `email`→`email_primary` | `eml_contacts.email` separate column (`db.py:135`) vs `contacts.email_primary` | present as parallel column (compat), no unified read view |
| alias EML `company`→company relationship | `eml_contacts.company` free text (`db.py:136`); `companies` never linked | **misplaced** |
| alias `products_misc`→company product info | `contacts.products_misc` (`db.py:70`) | present-unpopulated; no explicit mapping to `companies.product` |
| legacy: second contact person, extra comms info | no dedicated columns in either repo; closest: `email_secondary`/`phone_secondary`, and "contact 2" is aliased to `phone_secondary` (`parse.py:23`) | see open question Q6 |

### 3.3 EML staged contact (spec §3 → must migrate into unified staging)

| Spec field | `eml_contacts` column (`db.py:132-142`) | Status |
|---|---|---|
| id | `id` | present |
| name, email, phone_primary, phone_secondary, company, designation, address, city, pincode, website | same-named columns | present (47 rows) |
| source_email_id | FK `db.py:134` | present, populated (60 emails, 47 links) |
| source_file | `db.py:139` | present |
| dedup_status | `db.py:137` | present but **all 47 rows = 'NEW'** (forced by migration `db.py:264`); no CHECK constraint; not one of spec §4's dedup enum values |
| pushed_to_crm | `db.py:137` | present, all 47 = 1 — but `crm_contact_id` NULL in 47/47 → flag says pushed, link says not |
| created_at / updated_at | `db.py:141` | present |
| to_emails, cc_emails, bcc_emails | `db.py:139` | present |
| (§4 extras: review_status, validation, confidence, raw_source_data, import_status, duplicate_candidate_ids, extraction_run_id, source_row/page/sheet, reviewed_at) | — | **missing** (see §3.9) |

### 3.4 EML email (spec §3)

| Spec field | Current | Status |
|---|---|---|
| id, file_name, subject, date, sender_name, sender_email | `eml_emails` `db.py:121-128` | present (60 rows) |
| receiver_name, receiver_email | **no columns** — parsed by `services/eml_processor.py:64-65,161-162` then dropped by `insert_email` (`db.py:443-456`) | **missing** |
| body_text | present | present |
| has_signature | present | present |
| created_at | present | present |
| to_emails, cc_emails, bcc_emails | present | present |
| extra parsed metadata to preserve | `file_path`, `signature_block` (0 rows written), `processed_at` | present (keep) |
| emails never discarded for lack of contact | violated: `pipeline.py:145-147`; intake stores no email at all | **missing behavior** |
| one email ↔ MANY contacts / one contact ↔ MANY emails | no join table; ≤1 contact/email; contact→email only via `source_file` text | **missing** |

### 3.5 Call logs (spec §3) — all columns present, zero rows, zero writers

| Spec field | `call_logs` (`db.py:84-91`) | Status |
|---|---|---|
| contact_id, company_id, call_date, duration_minutes, call_type, outcome, notes, next_action, next_action_date, created_by, created_at | all present with FKs + indexes | **present-no-writer** (0 rows); IDs app-managed AUTOINCREMENT ✓; no code invents calls from email text (nothing writes at all) |

### 3.6 Import sessions / 3.7 Source records

| Spec field | Current | Status |
|---|---|---|
| session: file_name, sheet_name, upload_date, mapping, is_active, total_records, imported, skipped, user_id (legacy) | `session_data` `db.py:104-110` — **all present** | present-no-writer (0 rows; intake/pipeline never create sessions) |
| source record: session_id, data (raw JSON row), created_at | `records` `db.py:113-117` — all present | present-no-writer (0 rows) — **mandatory raw retention not implemented**; raw rows are discarded after `upsert_contact` (`pipeline.py:188-207`, `intake.py:93-112`) |

### 3.8 Profiles/users (spec §3 — not extraction targets; keep only for compat)

| Spec field | `users` (`db.py:96-100`) | Status |
|---|---|---|
| user email, name, provider UID, last login | present | present-no-writer (0 rows; `app.py` has no auth: "Loopback only, no auth") |
| profile names, work email | no columns | missing — **acceptable**: spec says keep only if migration compatibility requires; no writer exists |

### 3.9 Unified staging + three status dimensions (spec §4)

| Spec §4 requirement | Current | Status |
|---|---|---|
| ONE unified staging system for all 6 formats | none — XLSX/XLS/CSV/PDF/TXT go straight to `contacts` (`intake.py:106`, `pipeline.py:200`); EML has its own `eml_contacts` | **missing** (parallel paths exist today) |
| id, source_type, source_file, source_file_id, source_row, source_page, source_sheet, source_email_id | only fragments: `source_file`/`source_row` on `contacts` (never written), `source_email_id` on `eml_contacts`; **no source_type, source_page, source_sheet, source_file_id** anywhere (`NormalizedContact` lacks source_page/source_sheet — `services/adapters/__init__.py:12-33`) | **missing** |
| extracted + normalized contact fields | partially on `contacts` (also never written: `email_key`/`phone_key` are written only by upsert `db.py:427-429`) | **missing** as a staging concept |
| raw_source_data | `records.data` exists but unused | **missing** in the live path |
| field_evidence | `field_origin` column exists on `contacts`/`eml_contacts` (`db.py:72,140`) but 0 rows populated; adapters compute it and drop it | present-unpopulated (name mismatch: spec says `field_evidence`) |
| confidence | `NormalizedContact.confidence` exists (`services/adapters/__init__.py:33`), never persisted; `map_headers` computes confidence (`parse.py:78-81`) — only logged | **missing** |
| validation_status, validation_warnings | — | **missing** |
| dedup_status (enum NOT_CHECKED/UNIQUE/EXACT_DUPLICATE/PROBABLE_DUPLICATE/CONFLICT) | `eml_contacts.dedup_status` free text, all 'NEW' | **misplaced + wrong enum + no CHECK** |
| duplicate_candidate_ids | — | **missing** |
| review_status (NEW/NEEDS_REVIEW/READY/APPROVED/REJECTED/DISMISSED) | — | **missing** (no review UI/code anywhere: grep of `app.py`/`static/app.js` = 0 hits) |
| import_status (NOT_IMPORTED/NEW_CONTACT_CREATED/EXISTING_CONTACT_ENRICHED/IMPORT_FAILED) | only boolean `pushed_to_crm` | **missing** |
| crm_contact_id | `eml_contacts.crm_contact_id` — exists, NULL in 47/47 | present-unpopulated |
| extraction_run_id on staging | `contacts.extraction_run_id` exists (never written); not on `eml_contacts` | **missing** on staging |
| created_at/updated_at/reviewed_at | created/updated exist on `eml_contacts`; no reviewed_at | partial |
| THREE independent status dimensions (never merged) | today: one ambiguous `dedup_status` + one boolean `pushed_to_crm` | **missing** |
| Approval: create-if-missing / enrich-NULL-only / record conflicts | enrich-NULL-only exists for 11 fields (`db.py:419-424`); conflict recording does not; company resolve does not | partial |
| Merge preserves emails, source files, call logs, company links, notes, import history, provenance | no merge entity exists (silent `upsert_contact` enrich) | **missing** |
| Dedup keys: email, phone_key, name, company, website (priority ladder, no auto-merge of uncertain) | `email_key`/`phone_key` only (`db.py:304-311, 341-342`); name in-memory only (`DedupIndex`, `db.py:345-388`); company/website keys absent; current `DedupIndex` auto-merges on name alone (`db.py:384-387`) | partial + ladder not implemented |
| Field mapping: 25 types → canonical columns or raw preservation | `parse.ALIASES` covers 11 target fields (`parse.py:18-38`); adapters substring-match ~10; **unmatched headers are dropped** (`parse.py:72, 174-188`; warning only at `pipeline.py:181-183`); raw row never stored | **14+ types silently discarded**: product, industry, amount, date, status, id, keyword, location, facebook, member, fax, stdcode, other, skip (landline→phone_secondary, whatsapp→phone_primary are absorbed) |
| 10,000+ contacts, server-side pagination, indexed filtering | `list_contacts` uses `LIMIT ? OFFSET ?` + `LIKE '%q%'` (`db.py:480-494`) — OFFSET paging, unindexable search, `SELECT *` | partial (works at 55 rows, degrades at 10k+) |
| ONE SQLite DB; FKs; versioned migrations w/ backup + verification | one file ✓, WAL ✓, `foreign_keys=ON` ✓ but live `contacts.company_id` FK missing (§1.2); `_migration_log` exists but no backup step, no checksum/rollback recorded, exceptions swallowed | partial |
| FTS5 for search | none | missing (decide — see §7) |

---

## 4. Target DDL (SQLite)

Conventions (aligned with `CRM_Developer/docs/DATABASE_SCHEMA.md` §1): `INTEGER PRIMARY KEY` rowid PKs; timestamps `TEXT` ISO-8601 UTC; booleans `INTEGER` 0/1; JSON in `TEXT`; FKs declared with `ON DELETE` actions and enforced by `PRAGMA foreign_keys=ON` on every connection (already set at `db.py:23`). Every statement below is idempotent (`IF NOT EXISTS` / guarded) so it can run under `_migration_log` versioning.

### 4.1 Existing — unchanged

`call_logs` (`db.py:84-94`), `users` (`db.py:96-102`), `session_data` (`db.py:104-111`), `records` (`db.py:113-118`), `processed_files` (`db.py:150-153`), `extraction_runs` (`db.py:155-162`), `_migration_log` (`db.py:164-167`) — **keep as-is** (all spec fields already present; they need writers, not schema).

```sql
-- (no changes)
```

### 4.2 Altered (with compat notes)

```sql
-- ALTER A: eml_emails — add receiver fields the parser already produces
-- Compat: purely additive; insert_email() must start passing receiver_name/receiver_email.
ALTER TABLE eml_emails ADD COLUMN receiver_name TEXT;
ALTER TABLE eml_emails ADD COLUMN receiver_email TEXT;
CREATE INDEX IF NOT EXISTS idx_eml_emails_receiver_email ON eml_emails(receiver_email);

-- ALTER B: companies — website dedup key (additive)
ALTER TABLE companies ADD COLUMN website_key TEXT;
CREATE INDEX IF NOT EXISTS idx_companies_website_key ON companies(website_key);

-- ALTER C: contacts — rebuild required ONLY because the live DB's company_id has no FK
-- (ALTER TABLE cannot add a FOREIGN KEY). Fresh DBs already have it (db.py:65).
-- During the same rebuild, add the dedup keys the spec ladder needs.
-- Compat: copy all 26 existing columns 1:1; legacy `company`, `designation`, `website`,
-- `products_misc` columns are KEPT (populated data: designation 31/55, company text).
-- New columns: name_key, company_key, website_key (normalized dedup keys).
-- Resulting FK: company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL
--              extraction_run_id INTEGER REFERENCES extraction_runs(id) ON DELETE SET NULL
-- Indexes recreated verbatim from db.py:75-82 plus:
CREATE INDEX IF NOT EXISTS idx_contacts_created_at ON contacts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_contacts_city ON contacts(city);
CREATE INDEX IF NOT EXISTS idx_contacts_pincode ON contacts(pincode);
CREATE INDEX IF NOT EXISTS idx_contacts_name_key ON contacts(name_key);
CREATE INDEX IF NOT EXISTS idx_contacts_company_key ON contacts(company_key);
CREATE INDEX IF NOT EXISTS idx_contacts_website_key ON contacts(website_key);
```

**`eml_contacts` → compatibility VIEW** (after §5 backfill; spec: data migrates into the unified model, compatibility preserved):

```sql
-- Reads keep working for app._table("eml") (app.py:70-75) and list/get/update/delete.
-- WRITES must be redirected to staged_contacts in the same release:
--   db.insert_eml_contact (db.py:459), db.mark_pushed (db.py:476),
--   db.upsert_contact(table="eml_contacts") (pipeline.py:156), tests/test_db.py:33-45.
DROP TABLE eml_contacts;                      -- only after row-count verification (§5 v4/v5)
CREATE VIEW eml_contacts AS
SELECT id, source_email_id, name, email, phone_primary, phone_secondary,
       company, designation, address, city, pincode, website,
       dedup_status,                      -- mapped value, see §5 v4
       pushed_to_crm, crm_contact_id, source_file,
       to_emails, cc_emails, bcc_emails,
       field_evidence AS field_origin, email_key, phone_key,
       created_at, updated_at
FROM staged_contacts
WHERE source_type = 'EML';
```

### 4.3 New — unified staging + relationships + audit

```sql
-- NEW: unified staging table for ALL six formats (spec §4)
CREATE TABLE IF NOT EXISTS staged_contacts (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  source_type       TEXT NOT NULL
    CHECK (source_type IN ('XLSX','XLS','CSV','PDF','TXT','EML')),
  source_file       TEXT,                    -- file name
  source_file_id    TEXT                     -- processed_files.path (soft ref; ledger optional)
 REFERENCES processed_files(path) ON DELETE SET NULL,
  source_row        INTEGER,                 -- spreadsheet/PDF/TXT line
  source_page       INTEGER,                 -- PDF page
  source_sheet      TEXT,                    -- workbook sheet
  source_email_id   INTEGER REFERENCES eml_emails(id) ON DELETE SET NULL,

  -- extracted (as-given) contact fields
  name TEXT, email TEXT, phone_primary TEXT, phone_secondary TEXT,
  company TEXT, designation TEXT, address TEXT, city TEXT, pincode TEXT,
  website TEXT, whatsapp TEXT, position TEXT, files TEXT, products_misc TEXT,
  email_secondary TEXT,

  -- normalized / dedup keys (spec dedup ladder)
  email_key    TEXT,                          -- lower(trim(email))
  phone_key    TEXT,                          -- db.phone_key() digits (db.py:304-311)
  name_key     TEXT,                          -- lower(collapse_ws(name))
  company_key  TEXT,                          -- lower(collapse_ws(company))
  website_key  TEXT,                          -- host, lower, no 'www.'

  -- provenance / evidence
  raw_source_data TEXT,                       -- JSON: the untouched source row / page / headers
  field_evidence  TEXT,                       -- JSON: {field: "local"|"ai"|...}
  confidence      REAL,                       -- 0..1 from map_headers/adapters
  extraction_run_id INTEGER REFERENCES extraction_runs(id) ON DELETE SET NULL,

  -- three INDEPENDENT status dimensions (never merged)
  validation_status   TEXT NOT NULL DEFAULT 'UNVALIDATED'
    CHECK (validation_status IN ('UNVALIDATED','VALID','INVALID')),
  validation_warnings TEXT,                   -- JSON array
  review_status       TEXT NOT NULL DEFAULT 'NEW'
    CHECK (review_status IN ('NEW','NEEDS_REVIEW','READY','APPROVED','REJECTED','DISMISSED')),
  dedup_status        TEXT NOT NULL DEFAULT 'NOT_CHECKED'
    CHECK (dedup_status IN ('NOT_CHECKED','UNIQUE','EXACT_DUPLICATE','PROBABLE_DUPLICATE','CONFLICT')),
  duplicate_candidate_ids TEXT,               -- JSON array of staged/contact ids
  import_status       TEXT NOT NULL DEFAULT 'NOT_IMPORTED'
    CHECK (import_status IN ('NOT_IMPORTED','NEW_CONTACT_CREATED','EXISTING_CONTACT_ENRICHED','IMPORT_FAILED')),

  -- approval outcome
  crm_contact_id  INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
  pushed_to_crm   INTEGER NOT NULL DEFAULT 0, -- kept for eml_contacts view compat

  created_at  TEXT, updated_at TEXT, reviewed_at TEXT
);

-- Staging indexes: status queues (review/dedup/import), provenance, dedup keys, pagination
CREATE INDEX IF NOT EXISTS idx_staged_review_id      ON staged_contacts(review_status, id);
CREATE INDEX IF NOT EXISTS idx_staged_dedup          ON staged_contacts(dedup_status, id);
CREATE INDEX IF NOT EXISTS idx_staged_import         ON staged_contacts(import_status, id);
CREATE INDEX IF NOT EXISTS idx_staged_email_key      ON staged_contacts(email_key);
CREATE INDEX IF NOT EXISTS idx_staged_phone_key      ON staged_contacts(phone_key);
CREATE INDEX IF NOT EXISTS idx_staged_name_key       ON staged_contacts(name_key);
CREATE INDEX IF NOT EXISTS idx_staged_company_key    ON staged_contacts(company_key);
CREATE INDEX IF NOT EXISTS idx_staged_website_key    ON staged_contacts(website_key);
CREATE INDEX IF NOT EXISTS idx_staged_source_email   ON staged_contacts(source_email_id);
CREATE INDEX IF NOT EXISTS idx_staged_crm_contact    ON staged_contacts(crm_contact_id);
CREATE INDEX IF NOT EXISTS idx_staged_source_file    ON staged_contacts(source_type, source_file);
CREATE INDEX IF NOT EXISTS idx_staged_extraction_run ON staged_contacts(extraction_run_id);

-- NEW: email ↔ staged-contact M:N (one email yields many staged contacts;
-- one staged contact can span a thread of emails)
CREATE TABLE IF NOT EXISTS email_staged_links (
  email_id          INTEGER NOT NULL REFERENCES eml_emails(id) ON DELETE CASCADE,
  staged_contact_id INTEGER NOT NULL REFERENCES staged_contacts(id) ON DELETE CASCADE,
  created_at TEXT,
  PRIMARY KEY (email_id, staged_contact_id)
);
CREATE INDEX IF NOT EXISTS idx_email_staged_staged ON email_staged_links(staged_contact_id);

-- NEW: canonical contact ↔ email M:N (one contact ↔ many emails, one email ↔ many contacts)
CREATE TABLE IF NOT EXISTS contact_emails (
  contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  email_id   INTEGER NOT NULL REFERENCES eml_emails(id) ON DELETE CASCADE,
  origin     TEXT NOT NULL DEFAULT 'staged'    -- 'staged' | 'sender' | 'recipient'
             CHECK (origin IN ('staged','sender','recipient')),
  created_at TEXT,
  PRIMARY KEY (contact_id, email_id)
);
CREATE INDEX IF NOT EXISTS idx_contact_emails_email ON contact_emails(email_id);

-- NEW: merge audit — every merge is recorded; nothing is silently deleted
CREATE TABLE IF NOT EXISTS contact_merges (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  survivor_contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  merged_contact_id   INTEGER,                -- retained id (no longer a row) — provenance only
  reason              TEXT,                   -- 'exact_email' | 'exact_phone' | 'strong_composite' | 'manual'
  merged_by           TEXT,                   -- 'auto' | 'user' | NULL
  snapshot            TEXT,                   -- JSON of the losing row (full field dump)
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_contact_merges_survivor ON contact_merges(survivor_contact_id);

-- NEW: field-level conflicts from enrichment (local-wins records what it refused to overwrite)
CREATE TABLE IF NOT EXISTS field_conflicts (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  contact_id      INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  field_name      TEXT NOT NULL,
  existing_value  TEXT,
  incoming_value  TEXT,
  source_file     TEXT, source_row INTEGER, extraction_run_id INTEGER,
  status          TEXT NOT NULL DEFAULT 'OPEN'
    CHECK (status IN ('OPEN','RESOLVED')),
  resolved_value  TEXT, resolved_at TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_field_conflicts_contact ON field_conflicts(contact_id, status);
```

### 4.4 FTS5 (recommended, step v8)

```sql
-- Global search across contacts (name, email, phone, company, city) — see §7
CREATE VIRTUAL TABLE IF NOT EXISTS contacts_fts USING fts5(
  name, email_primary, email_secondary, phone_primary, phone_secondary,
  company, city, pincode,
  content='contacts', content_rowid='id', tokenize='unicode61'
);
-- Backfill: INSERT INTO contacts_fts(rowid, ...) SELECT id, ... FROM contacts;
-- Sync via AFTER INSERT/UPDATE/DELETE triggers on contacts (written in the migration).
```

### 4.5 Full FK graph (target)

```
users ──< session_data ──< records
users ──< extraction_runs ──< staged_contacts
eml_emails ──< staged_contacts (source_email_id)          eml_emails ──< email_staged_links >── staged_contacts
eml_emails ──< contact_emails >── contacts
companies ──< contacts (company_id)      companies ──< call_logs
contacts  ──< call_logs                   contacts ──< staged_contacts (crm_contact_id)
contacts  ──< field_conflicts             contacts ──< contact_merges (survivor)
contacts  ──< eml_contacts (VIEW target reads staged_contacts)
processed_files ──< staged_contacts (source_file_id, soft)
```

---

## 5. Migration plan (ordered, versioned, non-destructive)

Preconditions: app stopped (WAL writers quiescent); every step runs in one transaction and records itself in `_migration_log(version, name, applied_at, rollback_sql, checksum)` (`db.py:164-167`).

**Step 0 — Backup (mandatory, before anything):**
```sh
cp ~/.crm_local/crm.db ~/.crm_local/crm.db.bak.$(date +%Y%m%d%H%M%S)
cp ~/.crm_local/eml.db ~/.crm_local/eml.db.keep      # legacy source; do NOT delete (rollback source)
sqlite3 <backup> "PRAGMA integrity_check;"           # must print: ok
```

**Baseline verification (record these numbers first):**
```sql
SELECT 'contacts',count(*) FROM contacts UNION ALL SELECT 'companies',count(*) FROM companies
UNION ALL SELECT 'eml_emails',count(*) FROM eml_emails UNION ALL SELECT 'eml_contacts',count(*) FROM eml_contacts
UNION ALL SELECT 'call_logs',count(*) FROM call_logs UNION ALL SELECT 'session_data',count(*) FROM session_data
UNION ALL SELECT 'records',count(*) FROM records UNION ALL SELECT 'users',count(*) FROM users
UNION ALL SELECT 'processed_files',count(*) FROM processed_files
UNION ALL SELECT 'extraction_runs',count(*) FROM extraction_runs;
-- Live baseline (2026-11-07): 55, 0, 60, 47, 0, 0, 0, 0, 62, 0
```

| Ver | Name | Action | Verification (after) | Rollback |
|---|---|---|---|---|
| v2 | `eml_emails_receiver_cols` | `ALTER TABLE eml_emails ADD COLUMN receiver_name TEXT; … receiver_email TEXT;` + indexes (§4.2 A). Additive only. | `PRAGMA table_info(eml_emails)` shows both; row counts unchanged (60) | drop the two columns (`ALTER TABLE eml_emails DROP COLUMN …`, SQLite ≥3.35) or restore backup |
| v3 | `staging_tables` | Create `staged_contacts`, `email_staged_links`, `contact_emails`, `contact_merges`, `field_conflicts` + indexes (§4.3). `ALTER companies ADD website_key` (§4.2 B). | `sqlite_master` contains all 5; existing counts unchanged | `DROP TABLE` the 5 new tables (nothing references them yet) |
| v4 | `backfill_staged_from_eml` | `INSERT INTO staged_contacts (...) SELECT …, 'EML', … FROM eml_contacts;` — map old→new: `email`→`email`, `dedup_status='NEW'` → **`review_status='NEW'`, `dedup_status='NOT_CHECKED'`**, `pushed_to_crm`→`pushed_to_crm`, set `source_type='EML'`, `source_file`, `source_email_id`, `email_key`, `phone_key`, `raw_source_data` = json_object of the old row. | `SELECT count(*) FROM staged_contacts` = 47; `SELECT count(*) FROM staged_contacts WHERE source_email_id NOT IN (SELECT id FROM eml_emails)` = 0; per-table baseline unchanged | `DELETE FROM staged_contacts WHERE source_type='EML'` (eml_contacts untouched at this point) |
| v5 | `backfill_links_and_import_status` | (a) `INSERT OR IGNORE INTO email_staged_links SELECT source_email_id,id FROM staged_contacts WHERE source_email_id IS NOT NULL;` (b) resolve historical push: `UPDATE staged_contacts SET crm_contact_id=(SELECT c.id FROM contacts c WHERE c.email_key=staged_contacts.email_key), import_status='NEW_CONTACT_CREATED' WHERE pushed_to_crm=1 AND EXISTS(SELECT 1 FROM contacts c WHERE c.email_key=staged_contacts.email_key);` (c) rows still `pushed_to_crm=1` without a match get `validation_warnings=json_array('pushed_to_crm set before link existed')` and stay `NOT_IMPORTED` (truthful — see Q2). | `email_staged_links` count = 47; `SELECT count(*) FROM staged_contacts WHERE pushed_to_crm=1 AND crm_contact_id IS NULL AND validation_warnings IS NULL` = 0 | delete `email_staged_links`; reset import columns |
| v6 | `rebuild_contacts_fk_keys` | SQLite table rebuild inside a transaction: `CREATE TABLE contacts_new (… §4.2 C …); INSERT INTO contacts_new SELECT <26 cols>, lower(trim(name)), … FROM contacts;` verify count, `DROP TABLE contacts`, `ALTER TABLE contacts_new RENAME TO contacts;` recreate the 8 indexes from `db.py:75-82` + new ones. **Preserves all rows/cols; adds the missing company_id FK + name_key/company_key/website_key.** | `SELECT count(*) FROM contacts` = 55 (unchanged); `PRAGMA foreign_key_list(contacts)` shows company_id→companies; `PRAGMA integrity_check` = ok | restore backup file (step 0) |
| v7 | `eml_contacts_to_view` | Requires the **code writers of §4.2 to ship in the same release** (insert_eml_contact/mark_pushed/upsert_contact-table path/app._table/tests). Then: `DROP TABLE eml_contacts; CREATE VIEW eml_contacts AS … (§4.2)`. | `SELECT count(*) FROM eml_contacts` = 47 (via view); `INSERT` test through new writer lands in `staged_contacts` with `source_type='EML'`; app `/api/contacts?which=eml` returns 47 | recreate table from backup + re-run v4 backfill (data is still in `staged_contacts`) |
| v8 | `fts5_search` | Create `contacts_fts` + triggers + backfill (§4.4); `ANALYZE;` | `SELECT count(*) FROM contacts_fts` = 55; sample MATCH query returns rows | drop FTS table + triggers (search falls back to LIKE) |
| v9 | `verify_and_log` | Insert `_migration_log` rows for v2–v9 **with `rollback_sql` and `checksum`** (missing today, `db.py:197`). | final: `PRAGMA foreign_key_check` empty; `PRAGMA integrity_check` = ok; per-table counts == baseline (contacts 55, eml 60/47→staged 47) | — |

Final verification block (run after v9):
```sql
PRAGMA integrity_check;                 -- ok
PRAGMA foreign_key_check;               -- empty
SELECT count(*) FROM contacts;          -- = baseline (55)
SELECT count(*) FROM eml_emails;        -- = baseline (60)
SELECT count(*) FROM eml_contacts;      -- = baseline (47) via VIEW
SELECT count(*) FROM staged_contacts WHERE source_type='EML';  -- = 47
SELECT count(*) FROM email_staged_links;                        -- = 47
SELECT review_status,dedup_status,import_status,count(*) FROM staged_contacts GROUP BY 1,2,3;
```

**Rollback note:** steps v2–v5 are additive and individually reversible; v6/v7 change structure and roll back by restoring the step-0 backup (single-file restore; WAL checkpoint first: `sqlite3 crm.db "PRAGMA wal_checkpoint(TRUNCATE);"`). `eml.db` is never modified by any step — it remains an independent rollback source for the EML subset.

---

## 6. Approval / enrichment / merge data semantics (SQL-level patterns)

### 6.1 Approval (staged → canonical), inside one transaction

```sql
-- (1) missing contact? resolve/create company first (app-resolved, never LLM-invented)
UPDATE staged_contacts
SET company_id = (SELECT id FROM companies WHERE website_key = :website_key
                    OR (company_key IS NOT NULL AND company_key = :company_key) LIMIT 1)
WHERE id = :sid AND company_id IS NULL;
-- no company row? INSERT INTO companies (name, website_key, company_key, created_at) VALUES (…); then set company_id.

-- (2a) no existing contact → CREATE with provenance
INSERT INTO contacts (name, email_primary, phone_primary, company_id, address, city, pincode,
                      email_key, phone_key, name_key, company_key, website_key,
                      source_file, source_row, extraction_run_id, field_origin, created_at, updated_at)
SELECT s.name, s.email, s.phone_primary, s.company_id, s.address, s.city, s.pincode,
       s.email_key, s.phone_key, s.name_key, s.company_key, s.website_key,
       s.source_file, s.source_row, s.extraction_run_id, s.field_evidence, :now, :now
FROM staged_contacts s WHERE s.id = :sid
  AND NOT EXISTS (SELECT 1 FROM contacts c WHERE c.email_key = s.email_key OR c.phone_key = s.phone_key);
-- then: UPDATE staged_contacts SET import_status='NEW_CONTACT_CREATED', crm_contact_id=last_insert_rowid(), review_status='APPROVED', reviewed_at=:now WHERE id=:sid;
```

### 6.2 Local-wins enrichment (fill ONLY NULL/empty; never overwrite populated fields)

```sql
-- existing contact found → per-field fill; populated values are untouched by construction
UPDATE contacts SET
  name        = CASE WHEN name        IS NULL OR name=''        THEN :name        ELSE name END,
  email_primary = CASE WHEN email_primary IS NULL OR email_primary='' THEN :email ELSE email_primary END,
  phone_primary= CASE WHEN phone_primary IS NULL OR phone_primary='' THEN :phone ELSE phone_primary END,
  address     = CASE WHEN address     IS NULL OR address=''     THEN :address     ELSE address END,
  city        = CASE WHEN city        IS NULL OR city=''        THEN :city        ELSE city END,
  pincode     = CASE WHEN pincode     IS NULL OR pincode=''     THEN :pincode     ELSE pincode END,
  website     = CASE WHEN website     IS NULL OR website=''     THEN :website     ELSE website END,
  position    = CASE WHEN position    IS NULL AND designation IS NULL THEN :designation ELSE position END,
  company_id  = CASE WHEN company_id  IS NULL                    THEN :company_id  ELSE company_id END,
  updated_at  = :now
WHERE id = :cid;
-- (existing implementation of the same rule for 11 fields: db.py:419-424; add updated_at + provenance there)
```

### 6.3 Conflict recording (what local-wins refused to change)

```sql
INSERT INTO field_conflicts (contact_id, field_name, existing_value, incoming_value,
                             source_file, source_row, extraction_run_id, status, created_at)
SELECT :cid, 'city', c.city, :city, :sf, :sr, :er, 'OPEN', :now
FROM contacts c
WHERE c.id = :cid AND c.city IS NOT NULL AND c.city <> '' AND c.city <> :city;
-- run this per candidate field BEFORE the 6.2 UPDATE; later: resolve by writing resolved_value/resolved_at.
```

### 6.4 Provenance columns (every write carries them)

| Level | Columns |
|---|---|
| staged row | `source_file`, `source_row`, `source_page`, `source_sheet`, `source_email_id`, `source_type`, `extraction_run_id`, `field_evidence`, `raw_source_data` |
| canonical contact (first-touch) | `contacts.source_file`, `source_row`, `extraction_run_id`, `field_origin` (already exist — **start populating them**; today 0 rows, `db.py:434-439` omits them) |
| link/merge | `contact_emails.origin`, `contact_merges.snapshot`, `field_conflicts.source_file/source_row/extraction_run_id` |

### 6.5 Dedup normalization keys (exact functions already in repo)

```text
email_key   = lower(trim(email))                    -- db.normalize_email (db.py:341-342)
phone_key   = digits, strip '91' from 12, strip '0' from 11, ≥7 digits else NULL
              -- db.phone_key (db.py:304-311) / services/eml_dedup_rules.py:37-47 (identical)
name_key    = lower(collapse_ws(name))              -- eml_dedup_rules.normalize_name pattern (eml_dedup_rules.py:12-15)
company_key = lower(collapse_ws(company))
website_key = lower(host without scheme/'www'/trailing path)
```

Match ladder (staged → canonical): **1) exact `email_key` → 2) exact `phone_key` (≥10 digits; substring rule only as advisory) → 3) strong composite (name_key + company_key + city) → 4) name_key + company_key → 5) fuzzy (edit-distance/website) → set `dedup_status='PROBABLE_DUPLICATE'` + `duplicate_candidate_ids`, **never auto-merge**. Only tiers 1–2 may auto-set `EXACT_DUPLICATE`; tiers 3–4 → `PROBABLE_DUPLICATE`; failed comparison with data present → `CONFLICT`; pass with no candidates → `UNIQUE`. (Today's `DedupIndex.duplicate_reason` auto-merges on name alone, `db.py:384-387` — replace, don't extend.)

### 6.6 Merge preservation checklist (survivor keeps everything)

- [ ] emails: re-point `contact_emails.contact_id` → survivor; keep every `email_id` (no duplicates via PK)
- [ ] staged provenance: `UPDATE staged_contacts SET crm_contact_id=:survivor WHERE crm_contact_id=:loser`
- [ ] call logs: `UPDATE call_logs SET contact_id=:survivor WHERE contact_id=:loser` (FK CASCADE would otherwise delete them — do this **before** deleting the loser)
- [ ] company links: survivor keeps its `company_id` if set; loser's company_id only fills a NULL survivor (local-wins)
- [ ] notes/field conflicts: `UPDATE field_conflicts SET contact_id=:survivor WHERE contact_id=:loser`
- [ ] import history: never rewritten — `staged_contacts.import_status`/`crm_contact_id` retained; `contact_merges` row stores loser id + full JSON `snapshot`
- [ ] source files: `contacts.source_file` keeps first-touch value; additional sources remain reachable via staged rows / `contact_merges.snapshot`
- [ ] loser row deleted only after the `contact_merges` INSERT commits (same transaction); **never** delete `eml_emails`, `records`, or `raw_source_data`

---

## 7. Performance notes (10,000+ rows)

1. **Pagination — use keyset, not OFFSET.** Current `LIMIT ? OFFSET ?` (`db.py:481-492`) rescans skipped rows and drifts when rows are inserted during paging. Recommended pattern:
   ```sql
   -- unfiltered, newest-first
   SELECT * FROM contacts WHERE id < :cursor ORDER BY id DESC LIMIT :size;
   -- filtered queue (review view)
   SELECT * FROM staged_contacts WHERE review_status = :rs AND id < :cursor
   ORDER BY id DESC LIMIT :size;
   ```
   served by `idx_contacts_created_at` / `idx_staged_review_id (review_status, id)`; total counts via a separate `count(*)` (fine at 10k — SQLite counts a filtered scan in single-digit ms).
2. **Search — FTS5 is warranted.** The current `LIKE '%q%' OR …` over 4 columns (`db.py:484-490`) cannot use any index and runs per keystroke across 10k+ rows; it also searches `company` (a text column on contacts). Use the external-content FTS5 table (§4.4) with `unicode61` for words; if substring/phone-tail search is required, add a second FTS5 table with `tokenize='trigram'` (SQLite ≥3.34) rather than widening LIKE. Keep `email_key`/`phone_key` B-tree lookups for exact dedup/paste-search (already indexed, `db.py:81-82`).
3. **Indexes to keep in balance:** every new write path adds rows to ~10 indexes on `staged_contacts` — acceptable at 10k; run `ANALYZE` after each backfill so the planner picks the status-queue indexes. Avoid indexing low-cardinality columns alone (`import_status`, `source_type`) — they're only useful as the prefix of a composite `(status, id)` index, as designed in §4.3.
4. **Connection/pool:** single-process local app; WAL already on (`db.py:22`) with 30 s busy timeout (`db.py:20`) — sufficient; keep all writes in short transactions (intake currently holds one transaction for a whole batch, `intake.py:35-127` — commit per file to bound WAL growth).
5. **`SELECT *`** in `list_contacts`/`update_contact` (`db.py:485,492,498`) pulls `body_text`-scale columns once staging exists — project explicit column lists for list endpoints.
6. **Scale sanity:** 10k contacts ≈ 2–4 MB of rows; every indexed lookup here is O(log n) with tiny constants — the real risk at 10k is the unindexed LIKE search and OFFSET paging, both addressed above.

---

## 8. Open questions (concrete)

1. **`eml_contacts` → VIEW:** is read-compat via view acceptable (writes must be redirected to `staged_contacts` in the same release), or do you want the physical table kept and dual-written? Dual-write re-creates the parallel-staging pattern spec §4 forbids — recommend the view.
2. **Historical `pushed_to_crm=1` with NULL `crm_contact_id` (47/47 rows):** the backfill (v5c) marks unresolvable ones `NOT_IMPORTED` + a validation warning. Acceptable, or should they be recorded as `IMPORT_FAILED`? There is no evidence in the DB of what actually happened to them.
3. **`contacts` rebuild (v6)** is the only structural, data-moving step. Do it now (table = 55 rows) or defer until before the 10k bulk-load? Recommend now — cost only grows.
4. **`position` vs `designation`:** migrate the 31 populated `designation` values into `position` (spec alias) during v6 and stop writing `designation`, or keep both columns live? Recommend: backfill `position` from `designation` where `position IS NULL`, keep `designation` as a read-compat column.
5. **`products_misc` → `companies.product`:** the spec says "per explicit mapping" — which source columns feed it, and is the mapping per-file (stored in `session_data.mapping`) or global? Nothing populates either column today.
6. **"Second contact person / extra comms info" legacy fields:** no such columns exist in either repo (closest: `email_secondary`/`phone_secondary`, and "contact 2" aliased to phone at `parse.py:23`). Which fields did the spec mean?
7. **`source_file_id` FK → `processed_files.path`:** the ledger is written only by `pipeline.py:248` (intake never calls `mark_processed`), so intake-created staged rows would have NULL. Require intake to write the ledger, or keep `source_file_id` soft?
8. **`extraction_runs`:** should `intake.universal_intake` open a run row per batch (giving `extraction_run_id` real values), or is provenance by `source_file`/`source_row` enough for v1?
9. **Import sessions:** `session_data`/`records` have zero writers — is the review/reprocess/audit raw-row flow (spec §4 `raw_source_data` on `staged_contacts`) meant to *replace* `records`, or should intake also create a session + raw records per upload? Having both raw stores is duplication — recommend `staged_contacts.raw_source_data` as primary and leaving `records` for the legacy XLSX import-center flow only if that UI is built.
10. **FTS5 now or later:** ship v8 in the same migration train (one touching pass) or defer until search is actually built? Also decide tokenizer (`unicode61` vs `trigram`) based on whether users search phone tails/substring.

---

## Report

**Doc:** `docs/STAGED_CONTACT_ARCHITECTURE.md` (read-only investigation; no code, schema, or data modified).

**Top 5 findings**
1. **"Unified database" landed but is skin-deep:** one `crm.db` exists (`db.py:52-168`), yet the six formats have no unified staging — intake and pipeline upsert **directly into `contacts`** (`intake.py:106`, `pipeline.py:200`); `eml_contacts` remains a parallel EML-only staging table, exactly what spec §4 forbids.
2. **Spec §4 is almost entirely absent:** no review/import status, no validation/confidence persistence, no raw source rows, no merge/conflict/audit tables — only a free-text `dedup_status` (all 47 rows forced to `'NEW'`, `db.py:264`) and a boolean `pushed_to_crm` that claims 47/47 pushed while `crm_contact_id` is NULL in 47/47.
3. **Schema drift between fresh and live DB:** the live `contacts.company_id` has **no FK** (ALTER-added; `PRAGMA foreign_key_list(contacts)` empty) though `db.py:65` declares one — a fresh install and this install are different schemas; plus provenance columns (`source_row`, `field_origin`, `extraction_run_id`) exist but are populated in **0 rows**.
4. **Silent data loss paths:** 14+ of the 25 mapping types are discarded (`parse.py:72,174-188`), raw rows never stored (`records` unused), emails without contacts are dropped (`pipeline.py:145-147`), the intake EML path stores no email at all, and `receiver_name`/`receiver_email` are parsed (`eml_processor.py:64-65`) but have no column.
5. **6 of 11 tables are dead** (`companies`, `call_logs`, `users`, `session_data`, `records`, `extraction_runs` = 0 rows, zero writers), while `eml.db` still holds a duplicate copy of all 47/60 EML rows — prior docs are stale in both directions (`docs/LOCAL_PRODUCT_STATUS.md:29` cites a nonexistent `services/extraction.py`; `docs/IMPLEMENTATION_REPOSITORY_AUDIT.md:25` still says "2 separate DBs").

**Top 3 risks**
1. **Migrating `eml_contacts` to a view breaks three write paths** (`insert_eml_contact`, `mark_pushed`, `upsert_contact(table=…)`) plus `app._table("eml")` and two test files — code and DDL must ship in one release (v7), or the review queue silently stops accepting EML rows.
2. **The `contacts` rebuild (v6) is the only row-moving step** — run under a transaction with the step-0 backup and count verification; if skipped, the FK requirement and name/company/website dedup keys stay unenforceable on the live DB.
3. **Historical push state is unrecoverable** (47 rows claim pushed, no link) — any auto-classification of those rows into `import_status` invents history; the plan marks them `NOT_IMPORTED` + warning pending Q2.
