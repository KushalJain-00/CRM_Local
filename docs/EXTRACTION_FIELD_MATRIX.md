# Extraction Field Matrix

**Status:** Phase 0 investigation doc (read-only audit, no code changed)
**Author:** extraction-engineer (Round 1)
**Verified against:** CRM_Local @ `7610095` (clean tree) and reference repo CRM_Developer @ `d10db9f` + working tree
**Method:** every claim below was read from source; `file:line` citations are to CRM_Local unless prefixed `[Dev]`.

## Legend

| Marker | Meaning |
|---|---|
| ✅ | Implemented and wired end-to-end today |
| ⚠ | Present but partial, unwired, or wrong for this requirement |
| ❌ | Absent today (schema-only or nothing at all) |
| TARGET | Required behavior per master brief §5–§8 (not yet built) |

**Column key:** *AI role* is always "gap-fill only" or "never" per §5 — AI may never overwrite a populated local value and may never invent a value (`services/eml_processor.py:275-287` already implements local-wins for EML fields; this must become universal).

**Unmapped-preservation locations available today:** `records` table (`db.py:113-118`, `session_id` + JSON `data`) — exists in schema, **zero writers** in CRM_Local (grep: only `db.py` declares it). Reference implementation writes it at `[Dev] api/contacts.py:177-179` (`db.add(Record(session_id=session.id, data=item.raw_data))`). This is the designated target for all `unmapped_fields` / unmapped columns.

---

## A. Company fields — target table `companies` (`db.py:54-59`)

**Global finding:** the `companies` table and `contacts.company_id` exist in schema (`db.py:65`) but **no CRM_Local code ever INSERTs into `companies` or sets `company_id`** (grep across `*.py`, excluding `db.py`/tests: zero hits). Every row below is therefore ❌ at the persistence layer today.

| Field | Canonical target | Formats | Deterministic extraction method (current → required) | AI role | Validation rules | Evidence requirement | Unmapped preservation |
|---|---|---|---|---|---|---|---|
| name | `companies.name` | XLSX/XLS/CSV/PDF/TXT/EML | Current: `COMPANY_RE` suffix regex on signature (`services/eml_processor.py:22-26,182-184`); PDF block first-line + corporate-suffix heuristic (`services/parser.py:264-266`); header alias `company` (`parse.py:31-32`). TARGET: alias table + suffix regex (`Pvt/Ltd/LLP/Inc/Corp…`) + sheet header map, then entity-type classification (company vs product vs person) | Gap-fill only: may *identify* which string is the company when columns are ambiguous; never invent | Must not equal a product description or designation (§7 `Depth.- 900 FT. Borewell Pipeline Size.- 2.5 Inc` → SUSPICIOUS-as-company); no auto-merge of similar names (§8) | excerpt + location (`Sheet1, row 14` / `page 2` / `signature line 3`) + confidence | `records.data` / `unmapped_fields` |
| address | `companies.address` | XLSX/XLS/CSV/PDF/EML | Current: `LOCATION_PREFIX_RE` / `ADDRESS_LINE_RE` line scan (`services/eml_processor.py:41-48,199-212`); PDF address-keyword line join (`services/parser.py:282-286`); header alias (`parse.py:34`) | Gap-fill only (semi-structured PDF) | Preserve raw; split city/pincode only when source-supported (§6 ADDRESS AND LOCATION) | excerpt + location + confidence | `records.data` |
| city | `companies.city` | XLSX/XLS/CSV/PDF/EML | Current: `CITY_HINTS` 100+ city dictionary (`services/eml_processor.py:27-40`) applied to signature/address lines; header alias `city|town|district` (`parse.py:35`) | Gap-fill only | **Never infer city from company name** (§6); do not invent | excerpt + location + confidence | `records.data` |
| pincode | `companies.pincode` | XLSX/XLS/CSV/PDF/EML | Current: `\b\d{6}\b` on EML zone (`services/eml_processor.py:21,189-191`); `\b[1-9]\d{5}\b` on PDF text (`services/parser.py:172`); header alias (`parse.py:36`) | Gap-fill only | 6-digit India rule; must not fabricate (§6 "Do not invent Indian pincodes"); 5-digit/ZIP only if source is non-IN | excerpt + location + confidence | `records.data` |
| website | `companies.website` | XLSX/XLS/CSV/PDF/TXT/EML | Current: `WEBSITE_RE` with email-blanking first (`services/eml_processor.py:20,186-188`); header alias `website|web site|url|web|site` (`parse.py:37`) | Never (regex suffices) | Domain-shaped syntax; must not be an email or filename artefact (§6 EMAIL VALIDATION analog) | excerpt + confidence | `records.data` |
| industry | `companies.industry` | XLSX/XLS/CSV/PDF | **Nothing today.** TARGET: header alias family (`industry|sector|category|segment|business|trade`, cf. `[Dev] frontend/app.js:117` `detectField`) | Gap-fill only: designation ≠ industry disambiguation (§6) | Never copy `position`/`designation` into `industry` (disambiguation row H1) | excerpt + location + confidence | `records.data` |
| product | `companies.product` | XLSX/XLS/CSV/PDF | **Nothing today.** TARGET: header alias (`product|prod|service|item|goods|material|mfg`), multi-value join | Gap-fill only | Preserve technical descriptions; **never store product spec in company name or designation** (§6 PRODUCT INFORMATION) | excerpt + location + confidence | `records.data` |

---

## B. Canonical contact fields — target table `contacts` (`db.py:63-74`)

Writers today: `db.upsert_contact` (`db.py:409-440`, enrich-empty-only at `db.py:417-424`) called from `intake.py:106` and `pipeline.py:166,200`. Provenance columns `source_file/source_row/extraction_run_id/field_origin/email_key/phone_key` exist (`db.py:71-72`) but **`intake.py:94-105` drops `source_row`, `extraction_run_id`, `field_origin`, `whatsapp`, `email_secondary`, `phone_secondary`, `files`, `products_misc`** on every universal-intake write.

| Field | Canonical target | Formats | Deterministic method (current → required) | AI role | Validation rules | Evidence requirement | Unmapped preservation |
|---|---|---|---|---|---|---|---|
| name | `contacts.name` | all 6 | Header map alias `name|full name|contact person…` (`parse.py:29-30`); adapter substring `"name" in h` (`services/adapters/xlsx.py:30-31`, same in xls/csv/pdf); EML signature first-clean-line heuristic + `NAME_REJECT` (`services/eml_processor.py:50-55,219-257`); PDF block first line (`services/parser.py:257-268`) | Gap-fill only: may pick the right line as the name; may not invent | **`share the quotation asap.` → SUSPICIOUS sentence-as-name** (§7); reject greetings/departments (existing `NAME_REJECT`); ≥2 tokens for person names | excerpt + location + confidence | `records.data` |
| company_id | `contacts.company_id` → `companies.id` | all 6 | ❌ never set. TARGET: after company extraction, exact normalized-name link (§8: direct evidence required) | Gap-fill only: may propose link when evidence is in-source; never assume email domain = company (§6 COMPANY RESOLUTION) | Link only with direct evidence; no fuzzy company merge | link evidence excerpt | `records.data` |
| email_primary | `contacts.email_primary` + `email_key` | all 6 | `parse.clean_email` regex (`parse.py:10,156-158`); adapters lowercase `str(val).lower()` (`services/adapters/csv.py:28`); EML `EMAIL_RE` (`services/eml_processor.py:15,174-176`) with sender fallback (`:258-259`); PDF text regex (`services/parser.py:170`) | Gap-fill only | §7 syntax + **`image001.png@01dd4100.ede` → SUSPICIOUS artefact** (embedded-image name pattern); reject filename artefacts, keep unfamiliar domains; `email_key` = lowercased (`db.py:341-342`) | excerpt + location + confidence | `records.data` |
| email_secondary | `contacts.email_secondary` | XLSX/XLS/CSV | Alias table exists (`parse.py:19-23`, longest-first so `email 2` wins) ✅ in `parse.map_headers`; ⚠ adapters map any header containing `email` to `email_primary` and **overwrite** (`services/adapters/xlsx.py:32-33`) | Never (regex) | Same as primary; never silently promote secondary → primary (§6 "primary vs secondary") | excerpt + location + confidence | `records.data` |
| phone_primary | `contacts.phone_primary` + `phone_key` | all 6 | `parse.clean_phone` ≥7 digits + Excel sci-notation fix (`parse.py:161-171`); adapters `"phone"/"mobile" in h` (`xlsx.py:34-35`); TXT line regex (`services/adapters/txt.py:23`); EML `PHONE_RE` (`eml_processor.py:16-19,177-181`); PDF (`parser.py:168-169`) | Never (regex suffices) | Preserve original string; distinguish mobile/landline/STD/secondary; **do not invent country code; do not assume mobile** (§6 PHONE VALIDATION); `phone_key` India collapse (`db.py:304-311`, `services/eml_dedup_rules.py:37-47`) | excerpt + location + confidence | `records.data` |
| phone_secondary | `contacts.phone_secondary` | XLSX/XLS/CSV/EML | Alias table (`parse.py:21-23`) ✅ in `map_headers`; EML joins extra phones (`eml_processor.py:180-181`); ⚠ adapters never set it | Never | Same as primary; multi-value → keep list in staging, first value in canonical (cf. `[Dev] api/eml.py:44-49`) | excerpt + location | `records.data` |
| phone_country | `contacts.phone_country` (default `'IN'`, `db.py:68`) | all 6 | ⚠ default only; **no code computes it in CRM_Local**. TARGET: derive from explicit `+<cc>` prefix only (`[Dev] api/contacts.py:58-72` `classify_phone` is the reference implementation, not present in Local) | Never | "Do not invent a country code" (§6); unknown → leave default or NULL, never guess | prefix excerpt | `records.data` |
| whatsapp | `contacts.whatsapp` | XLSX/XLS/CSV/TXT | ❌ never populated. Alias `whatsapp` currently routes to **phone_primary** (`parse.py:27`). TARGET: dedicated mapping type (`[Dev] frontend/app.js:37`) | Never | **Evidence-only**: number enters `whatsapp` only when the source labels it WhatsApp (§6) | label excerpt + location | `records.data` |
| position | `contacts.position` | all 6 | ⚠ column exists; adapters/parse write the **legacy `designation`** column instead (`db.py:69`); `position` never written in Local. `[Dev] services/data_access.py:136-138` maps designation→position | Gap-fill only (signature role line) | §6 POSITION AND DESIGNATION: `position` is canonical, EML staging uses `designation` — map consistently, never to `industry` | excerpt + location | `records.data` |
| designation (legacy) | `contacts.designation` | all 6 | Aliases `designation|job title|title|role|position|department` (`parse.py:33`); adapters `title/position` (`xlsx.py:38-39`); EML next-line role keyword (`eml_processor.py:247-255`) | Gap-fill only | Same as position; never an industry (H1) | excerpt + location | `records.data` |
| city | `contacts.city` | all 6 | As company.city above | Gap-fill only | No inference from company name | excerpt + location | `records.data` |
| address | `contacts.address` | all 6 | As company.address above | Gap-fill only | Preserve raw; no invention | excerpt + location | `records.data` |
| pincode | `contacts.pincode` | all 6 | As company.pincode above | Gap-fill only | No invented pincodes | excerpt + location | `records.data` |
| files | `contacts.files` | XLSX/XLS/CSV | ❌ never written (schema `db.py:70`; `[Dev]` maps mapping-type `files` → `Files` at `frontend/app.js:607`) | Never | Filename list preserved verbatim | location | `records.data` |
| products_misc (legacy) | `contacts.products_misc` | XLSX/XLS/CSV | ❌ never written (schema `db.py:70`; `[Dev]` feeds it from mapping types `product`+`industry`, `frontend/app.js:609`) | Gap-fill only | Technical text allowed here; must not leak into `company`/`position` (H2) | excerpt | `records.data` |
| email (EML contract key) | → `contacts.email_primary` | EML | Contract key `email` in `FIELD_KEYS` (`services/eml_processor.py:7`) mapped to `email_primary` at `pipeline.py:134`, `intake.py:82`, `services/adapters/eml.py:27` | Gap-fill only | Same as email_primary | excerpt | `records.data` |
| company (text, legacy) | `contacts.company` | all 6 | Header alias (`parse.py:31-32`); EML `COMPANY_RE` | Gap-fill only | Domain ≠ company evidence (H3) | excerpt + location | `records.data` |
| source_file / source_row / extraction_run_id / field_origin / confidence | provenance columns (`db.py:71-72`) | all 6 | ⚠ `NormalizedContact` carries all of them (`services/adapters/__init__.py:29-33`) but: `intake.py:94-105` drops them; `pipeline._process_eml` never sets `field_origin` (`pipeline.py:131-144`); `extraction_runs` table (`db.py:155-161`) has **zero writers** in Local; per-field evidence (`excerpt/location/confidence`) does not exist anywhere — only a whole-contact float default `0.0` (`adapters/__init__.py:33`) and a *column-mapping* confidence (`parse.py:74-81`) | Never (bookkeeping) | Evidence required **per populated field** (§6 EVIDENCE REQUIREMENTS) — this is the biggest structural gap | this row *is* the evidence carrier | n/a |

---

## C. EML staged contact — target table `eml_contacts` (`db.py:132-142`)

**Only writer:** `db.insert_eml_contact` (`db.py:459-473`), called only from `pipeline._process_eml` (`pipeline.py:161`). The universal-intake path **bypasses staging entirely** and writes canonical `contacts` directly (`intake.py:106`).

| # | Field | Formats | Deterministic method (current → required) | AI role | Validation | Evidence | Unmapped |
|---|---|---|---|---|---|---|---|
| 1 | source_email_id | EML | FK to `eml_emails.id` set by `insert_eml_contact` (`db.py:461`) ✅ | Never | integrity FK | n/a | n/a |
| 2 | source_file | EML | basename (`pipeline.py:161` via `source_file` arg) ✅ | Never | n/a | n/a | n/a |
| 3 | name | EML | signature heuristic (`eml_processor.py:219-257`) ✅ | Gap-fill | sentence-as-name → SUSPICIOUS (H4) | excerpt | `records.data` |
| 4 | email | EML | `EMAIL_RE` + sender fallback (`eml_processor.py:174-176,258-259`) ✅ | Gap-fill | artefact rules (`image001.png@…` → SUSPICIOUS) | excerpt | `records.data` |
| 5 | phone_primary | EML | `PHONE_RE` (`eml_processor.py:16-19,177-179`) ✅ | Never | India/INTL rules | excerpt | `records.data` |
| 6 | phone_secondary | EML | joined extras (`eml_processor.py:180-181`) ✅ | Never | first-value in canonical | excerpt | `records.data` |
| 7 | company | EML | `COMPANY_RE` (`eml_processor.py:22-26,182-184`) ✅ | Gap-fill | technical text ≠ company (H5) | excerpt | `records.data` |
| 8 | designation | EML | next-line role keywords (`eml_processor.py:247-255`) ✅ | Gap-fill | ≠ industry | excerpt | `records.data` |
| 9 | address | EML | prefix/line scan (`eml_processor.py:41-48,199-212`) ✅ | Gap-fill | no invention | excerpt | `records.data` |
| 10 | city | EML | `CITY_HINTS` (`eml_processor.py:27-40,204-217`) ✅ | Gap-fill | no inference from company name | excerpt | `records.data` |
| 11 | pincode | EML | `\b\d{6}\b` (`eml_processor.py:21,189-191`) ✅ | Gap-fill | no invented pincodes | excerpt | `records.data` |
| 12 | website | EML | `WEBSITE_RE` email-blanked (`eml_processor.py:186-188`) ✅ | Never | not an email/filename | excerpt | `records.data` |
| 13 | to_emails | EML | MIME `To` header (`eml_processor.py:116,120,163`) — ⚠ **column exists (`db.py:139`) but `insert_eml_contact` never writes it** (`db.py:460-464` omits the three list columns); `EmlAdapter` computes them (`services/adapters/eml.py:22-24`) and `intake.py:94-105` then drops them | Never (MIME authoritative) | header parsing only | n/a | n/a |
| 14 | cc_emails | EML | MIME `Cc` (`eml_processor.py:117,164`) — same drop as #13 | Never | | n/a | n/a |
| 15 | bcc_emails | EML | MIME `Bcc` (`eml_processor.py:118,165`) — same drop as #13 | Never | | n/a | n/a |
| 16 | dedup_status | EML | set by pipeline: `"new"` or upsert path (`pipeline.py:161`); migration writes `"NEW"` (`db.py:264`) — ⚠ case-inconsistent, no NOT_CHECKED/UNIQUE/EXACT/PROBABLE/CONFLICT vocabulary (§ product brief) | Never | must come from dedup engine, not LLM | n/a | n/a |
| 17 | pushed_to_crm | EML | `db.mark_pushed` (`db.py:476-477`) ✅ — ⚠ `crm_contact_id` column (`db.py:138`) is **never populated** (mark_pushed only flips the flag) | Never | | n/a | n/a |

**Contract gap:** §6 `contacts[]` in the JSON contract also requires `whatsapp`, `phone_country`, `files` — none exist on `eml_contacts`; staging schema must be extended or the contract subset documented.

---

## D. EML email record — target table `eml_emails` (`db.py:121-128`)

**Only writer:** `db.insert_email` (`db.py:443-456`), called from `pipeline.py:149`.

| Field | Current method | Status | AI role | Validation / note |
|---|---|---|---|---|
| file_name | basename (`db.py:449`) | ✅ | Never | |
| file_path | full path (`db.py:449`) | ✅ | Never | provenance |
| subject | MIME `Subject` (`eml_processor.py:157`) | ✅ | Never | MIME authoritative (§6 C) |
| date | MIME `Date` raw string (`eml_processor.py:158`) | ✅ | Never | unnormalized; keep raw + add normalized |
| sender_name / sender_email | `email.utils.getaddresses(From)` (`eml_processor.py:89-96,115`) | ✅ | Never | |
| receiver_name / receiver_email | parsed (`eml_processor.py:116,161-162`) | ❌ | Never | **Not in schema** (`db.py:121-128`) and not in `insert_email` column list (`db.py:445-447`) — parsed then discarded; §6 C requires both |
| to_emails / cc_emails / bcc_emails | MIME headers, CC/BCC appended to receiver (`eml_processor.py:120-131,163-165`) | ✅ | Never | recipients must not be invented from body mentions (§6 C) |
| body_text | MIME text/plain→html fallback, quoted-history strip, ≤8000 chars (`eml_processor.py:133-153,166`) | ✅ | Never | untrusted content zone |
| has_signature | `SIG_DELIM` + trailing-cluster heuristic (`eml_processor.py:98-111`) | ✅ | Never | |
| signature_block | same (`eml_processor.py:103,168`) | ⚠ parsed ✅ but **never persisted** — absent from `insert_email` (`db.py:445-447`) | Never | needed as evidence source for signature-derived fields |
| processed_at / created_at | `now_iso()` (`db.py:454-455`) | ✅ | Never | LLM must never generate (§6 rule) |
| file-level classification (contacts vs companies vs emails vs calls vs products vs other) | ❌ absent | ❌ | Gap-fill may *classify*; deterministic pre-checks (has @ / has phone / has table) must gate first | §5 General: never force every file into a contact |

---

## E. Call logs — target table `call_logs` (`db.py:84-94`)

**Status: table exists, zero writers, zero readers, no adapter supports call extraction** (grep: `call_logs` appears only in `db.py`). §6 D gates this: only when the source *explicitly* contains structured call information.

| # | Contract field (§6 D) | DB column | Deterministic method (required) | AI role | Validation | Evidence |
|---|---|---|---|---|---|---|
| 1 | contact_name | (resolve → `contact_id`) | header alias `call/contact name`; must match an extracted contact or be kept staged | Gap-fill | not an invented person | excerpt + location |
| 2 | company_name | (resolve → `company_id`) | header alias `company` | Gap-fill | direct evidence only | excerpt + location |
| 3 | call_date | `call_date` | date column parse (`services/parser.py:56-60` xldate handling reusable) | Never | reject non-dates | cell excerpt |
| 4 | duration_minutes | `duration_minutes` | numeric cell / `HH:MM` parse | Never | integer ≥0 | cell excerpt |
| 5 | call_type | `call_type` | enum from header/value (`inbound/outbound/meeting`) | Gap-fill | unknown → NULL | excerpt |
| 6 | outcome | `outcome` | free text cell | Gap-fill | no invention | excerpt |
| 7 | notes | `notes` | cell/row text | Gap-fill | untrusted | excerpt |
| 8 | next_action | `next_action` | cell text | Gap-fill | no invention | excerpt |
| 9 | next_action_date | `next_action_date` | date parse | Never | valid date | excerpt |
| 10 | contact link | `contact_id` (`db.py:86`) | backend resolution at stage time | Never | LLM never emits DB IDs (§6 rule) | n/a |
| 11 | company link | `company_id` (`db.py:87`) | backend resolution at stage time | Never | LLM never emits DB IDs | n/a |

(Audit columns `created_by`, `created_at` at `db.py:89-90` are backend-written, not extraction fields.)

---

## F. Import session, source record, and run provenance

| Entity / field | Target | Status today | Required method | AI role | Evidence / preservation |
|---|---|---|---|---|---|
| session: file_name, sheet_name, upload_date, mapping, user_id, total_records, imported, skipped, is_active, created_at (`db.py:104-110`) | `session_data` | ❌ schema only, zero writers | one row per import run; `mapping` stores the user-confirmed column→type map (reference: `[Dev] api/contacts.py:43-50` `BatchImportRequest.mapping`) | Never | raw mapping stored verbatim |
| record: id, session_id, data, created_at (`db.py:113-118`) | `records` | ❌ schema only, zero writers | one row per **raw source row** archived before normalization — this is the unmapped-preservation home (reference `[Dev] api/contacts.py:177-179`) | Never | full original row JSON |
| run: id, user_id, started_at, completed_at, status, files_processed, contacts_found, error, config_snapshot (`db.py:155-161`) | `extraction_runs` | ❌ zero writers in Local (reference `[Dev] services/data_access.py` `create_extraction_run`, used at `[Dev] api/intake.py:57-60`) | written by the single orchestrator; `config_snapshot` must **mask API keys** | Never | n/a |
| ledger: path, size, mtime, status, detail, contacts_found, processed_at (`db.py:150-153`) | `processed_files` | ✅ (`db.py:523-536`, used `pipeline.py:101,248-260`) | keep as-is, owned by orchestrator | Never | n/a |

---

## G. The 25 mapping types

**Origin:** taxonomy lives in the reference frontend — `[Dev] frontend/app.js:21-47` (`const FT`) and auto-detection `detectField()` at `[Dev] frontend/app.js:100-158`; type→standard-column conversion `normalizeToStandardFields()` at `[Dev] frontend/app.js:586-640`. **CRM_Local has none of it** (grep `stdcode|landline|facebook` → 0 hits in Python; `parse.ALIASES` covers only 11 contact fields, `parse.py:18-38`). Local's `session_data.mapping` is the intended home for the saved type map (F above).

| # | Mapping type | Target column / preservation location | Deterministic detection (from reference, to be ported server-side) | AI role | Validation note |
|---|---|---|---|---|---|
| 1 | company | `contacts.company` → `companies.name` (`app.js:597`) | header `company|firm|party|organisation…` (`app.js:116`) | Gap-fill | H5: technical text ≠ company |
| 2 | contact | `contacts.name` (Person Name 1/2, `app.js:602-603`) | header `contact person|person|director|proprietor…` (`app.js:115`) | Gap-fill | H4: sentence ≠ name |
| 3 | phone | `contacts.phone_primary`/`phone_secondary` (`app.js:604-605`) | header `mob|mobile|phone…` or value-shape (`app.js:111-112`) | Never | India/INTL classify; no invented cc |
| 4 | email | `contacts.email_primary`/`email_secondary` (`app.js:606-607`) | header `email|mail` or value contains `@` (`app.js:104-105`) | Never | artefact rejection |
| 5 | address | `contacts.address` (`app.js:599`) | header `address|street|road|plot…` (`app.js:119`) | Gap-fill | preserve raw |
| 6 | city | `contacts.city` (via `Location`, `app.js:598`) | header `city|town|district|dist|taluka|state…` (`app.js:118`) | Gap-fill | no company-name inference |
| 7 | pincode | `contacts.pincode` (`app.js:600`) | header `pin|zip|postal` or all-values 5–6 digits (`app.js:113-114`) | Never | 6-digit IN rule, no invention |
| 8 | website | `contacts.website` (`app.js:601`) | header `web|site|url|www` or `http(s)://` value (`app.js:106-107`) | Never | not an email |
| 9 | product | `contacts.products_misc` → `companies.product` (`app.js:609`) | header `product|prod|service|item|goods|mfg…` (`app.js:120`) | Gap-fill | H2 |
| 10 | industry | `companies.industry` (folded into `products_misc` in reference, `app.js:609`) | header `industry|sector|category|segment|business` (`app.js:121`) | Gap-fill | H1: ≠ designation |
| 11 | amount | **preserve only** → `records.data` (no CRM column) | header `amount|value|price|cost|revenue|invoice…` (`app.js:109`) | Never | must not be mistaken for phone/pincode |
| 12 | date | **preserve only** → `records.data` (call-log dates excepted) | header `date|dt|time|year|month|day` (`app.js:110`) | Never | valid-date parse |
| 13 | status | **preserve only** → `records.data` | header `status|stage|state|active` (`app.js:114`) | Never | |
| 14 | id | **preserve only** → `records.data`; source row number | header `srno|sno|serialno|no|#` or sequential numeric (`app.js:101-103`) | Never | never a phone (§6 ID vs phone) |
| 15 | keyword | `contacts.products_misc`/`records.data` (reference: `keyword` → Designation, `app.js:604`) ⚠ conflicting use in reference | header `keyword|tag|category|type` (`app.js:117`) | Gap-fill | must not overwrite real designation |
| 16 | location | `contacts.city` (`app.js:598` merges city+location) | exact header `location` (`app.js:118`) | Gap-fill | address vs city split only with evidence |
| 17 | facebook | **preserve only** → `records.data` (no CRM column) | header `facebook|fb.com|social` (`app.js:106`) | Never | URL syntax check |
| 18 | member | **preserve only** → `records.data` | header `member|memb` (`app.js:111`) | Never | boolean-ish |
| 19 | fax | **preserve only** → `records.data` (candidate `phone_secondary` later, evidence-only) | header `fax` (`app.js:108`) | Never | not a phone unless labeled |
| 20 | whatsapp | `contacts.whatsapp` (`app.js:606` Mobile/WhatsApp) | header `whatsapp|whats|wa no` (`app.js:107`) | Never | **label evidence required** |
| 21 | files | `contacts.files` (`app.js:608`) | header `file|attachment` | Never | verbatim |
| 22 | stdcode | **preserve only** → `records.data` (compose with landline) | header `stdcode|std` (`app.js:108`) | Never | never a standalone phone |
| 23 | landline | **preserve only** → `records.data`; compose `stdcode+number` → `phone_secondary` with evidence | header `landline` / `telephone` (`app.js:109-110`) | Never | §6: do not assume mobile |
| 24 | other | **preserve only** → `records.data` + surfaced as `unmapped_fields` | fallback, confidence 45 (`app.js:157`) | Gap-fill may *suggest* a type, human confirms | never silently discarded (§6 UNMAPPED) |
| 25 | skip | **preserve only** → `records.data` (raw kept even when excluded) | user choice (`app.js:46`) | Never | raw row archived regardless |

---

## H. Disambiguation rules (must be enforced by validator + prompt, one row each)

| # | Rule (brief §6/§7) | Violating example that must be flagged | Enforcement point | Status today |
|---|---|---|---|---|
| H1 | **designation ≠ industry** — `position`/`designation` never receives an industry value and vice versa | header `Industry` auto-mapped by adapters' loose `"name" in h` matching? (adapters have no industry key at all — `services/adapters/xlsx.py:29-47`) | validator: `industry` value containing role keywords (`manager|director|engineer|ceo…` from `eml_processor.py:253`) → `FIELD_MAPPING_ERROR` | ❌ no check |
| H2 | **product ≠ company name / designation** | `Depth.- 900 FT. Borewell Pipeline Size.- 2.5 Inc` offered as company name → `SUSPICIOUS` (§7) | validator: company-name heuristic (spec + measurement patterns `FT.|Inc\b|\d+\s*(mm|inc|ft)`) → `SUSPICIOUS` | ❌ no check (PDF block currently *would* accept similar strings via `services/parser.py:264-266` suffix regex only — pattern is narrower but unvalidated) |
| H3 | **email domain ≠ company evidence** | `john@acme.com` ⇒ company "Acme" | prompt rule (§6 COMPANY RESOLUTION) + validator flags company links whose only evidence is a domain → `UNCERTAIN` | ⚠ website extraction blanks emails (`eml_processor.py:186`) but no company-from-domain guard exists |
| H4 | **sentence ≠ name** | `share the quotation asap.` as `name` → `SUSPICIOUS` (§7) | validator: name ending in `.`, >8 tokens, greeting verbs → `SUSPICIOUS`; `NAME_REJECT` (`eml_processor.py:50-55`) is the existing partial seed | ⚠ partial (EML only), ❌ for spreadsheets/PDF |
| H5 | **technical text ≠ company name** | `Depth.- 900 FT. Borewell Pipeline Size.- 2.5 Inc` → `SUSPICIOUS` as company (§7), preserved not dropped | validator as H2; value still stored raw + flagged | ❌ |
| H6 | **ID/reference number ≠ phone** | `SR.NO 9876543210` / order IDs | validator: 10–13 digit value in an `id`-typed column → `SUSPICIOUS`; phone must come from phone-typed column or explicit formatting (+, spaces, `mobile` label) | ⚠ `parse.py` requires phone-typed header, but TXT/PDF regexes (`adapters/txt.py:23`, `parser.py:168-169`) grab any digit run → `UNCERTAIN` |
| H7 | **sender/recipient/mentioned ≠ contact** | every body name becomes a contact | EML adapter emits **at most one** staged contact today (`services/adapters/eml.py:39`) — under-extraction vs §6 "extract every genuinely identifiable contact"; TARGET: sender/signature/mentioned roles labeled separately in contract (`contact_indices` + evidence) | ⚠ wrong direction (drops rather than mislabels) |
| H8 | **a real email must not be rejected for unfamiliar domain** | `x@mynewstartup.xyz` dropped | validator syntax-only rejection; never heuristic-reject by TLD/domain age | ⚠ `llm.parse_json` rejects on regex only (`llm.py:66-68`) — acceptable; no domain blacklist exists (good) |

---

## Summary of coverage gaps (top of backlog for Phase 1)

1. **No `companies`/`call_logs`/`session_data`/`records`/`extraction_runs` writers at all** — schema-only tables (`db.py:54-161`).
2. **No per-field evidence structure** (`excerpt/location/confidence`) anywhere; `NormalizedContact.field_origin` is a source-label dict only (`adapters/__init__.py:32`) and is dropped by intake (`intake.py:94-105`).
3. **No unified validation service** — three partial validators (`parse.clean_email/parse.clean_phone` `parse.py:156-171`, `llm.parse_json` `llm.py:47-73`, and none for names/companies/pincodes); no issue categories (`INVALID/SUSPICIOUS/MISSING/UNCERTAIN/FIELD_MAPPING_ERROR/POSSIBLE_DUPLICATE/CONFLICT` appear in **no** source file — grep confirmed).
4. **Adapter-level header mapping is substring-loose and duplicates `parse.py` alias logic** (`xlsx.py:29-47` vs `parse.py:18-38`): `Email 2` overwrites `email_primary`, `whatsapp` lands in `phone_primary`, no secondary phones.
5. **Staging bypass:** universal intake writes canonical `contacts` directly with no validation, no dedup index, no review status (`intake.py:106`).
