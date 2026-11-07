# Advanced Extraction Specification

**Status:** Phase 0 investigation + target design (read-only audit; no code changed)
**Author:** extraction-engineer (Round 1)
**Scope:** §5 two-layer extraction, §6 master prompt + JSON contract, §7 validation, §8 dedup/enrichment, §12 provider manager, §13 one-orchestrator rule.
**Evidence rule:** every *current-state* claim carries a `file:line` citation to CRM_Local @ `7610095`, or `[Dev]` prefix for CRM_Developer @ `d10db9f`. Known-stale docs (`docs/LOCAL_PRODUCT_STATUS.md`, `docs/IMPLEMENTATION_REPOSITORY_AUDIT.md`) were not trusted; the phantom `services/extraction.py` claim is confirmed stale — `grep` shows `services/extraction.py` exists only in the reference repo (`CRM_Developer/services/extraction.py`), and `docs/LOCAL_PRODUCT_STATUS.md:29` asserts it for CRM_Local incorrectly.

---

## 1. Current architecture (verified)

### 1.1 Adapter layer + registry — EXISTS, thin, duplicated logic

- Protocol `ExtractionAdapter` (`can_handle`, `extract`) with `NormalizedContact` + `ExtractionResult`: `services/adapters/__init__.py:45-49`, `:12-43`.
- Registry: eager import `:53`, lazy singleton `_collect_adapters()` returning the 6 instances in fixed order `:58-70`, `get_adapter()` first-match `:73-78`, `dispatch()` name-only helper `:81-84` (used only by tests, `tests/test_adapters.py:11-35`).
- All six adapters are byte-identical to the reference repo (`cmp` verified: `services/adapters/{__init__,csv,eml,pdf,txt,xls,xlsx}.py`).
- **What each adapter actually does:**

| Adapter | Mechanism | Limits vs §5 |
|---|---|---|
| `xlsx.py` | openpyxl, **first row = header** (`:24`), substring header match `"name" in h` etc. (`:29-47`) | no header-row detection, no repeated-header skip, no merged cells, no multi-contact, `Email 2` overwrites `email_primary` (`:32-33`), no sheet-name/row evidence beyond `source_row` (`:26`) |
| `xls.py` | wraps `services/parser.parse_xls` then re-does substring mapping (`:18-46`) | same mapping flaws; parser merges all sheets into one header union (`services/parser.py:74-75`) so sheet separation is lost |
| `csv.py` | fixed `utf-8-sig`, first row header, substring mapping (`:15-42`) | **no delimiter sniffing, no encoding fallback** — while `parse.parse_csv` (`parse.py:118-137`) *does* sniff delimiters: two divergent CSV implementations in one repo |
| `pdf.py` | wraps `services/parser.parse_pdf` + substring mapping (`:18-45`) | parser does tables + text fallback (`services/parser.py:93-155`) but **page numbers are discarded** (`:87,129-131`), no letterhead/business-card/signature blocks, no company-vs-contact separation |
| `txt.py` | phone regex per line only (`:23`) | no names, no contact lists, no prose guard (§5 TXT: "avoid treating arbitrary prose as a contact" — any line with a 10-digit run becomes a contact) |
| `eml.py` | `parse_eml_bytes` + `extract_local_fields`, Layer-1 only (`:18-21`), sets `to/cc/bcc` on the contact dict (`:22-24`) | those three are then dropped by the intake writer (§1.3); emits at most **one** contact per email (`:39`) — contradicts §6 MULTIPLE CONTACTS / §5 EML sender-vs-signature-vs-mentioned distinction |

- `ExtractionResult.local_only` (`:42`) is set but **never read** by any orchestrator; `NormalizedContact.confidence` default `0.0` (`:33`) is never assigned by any adapter.

### 1.2 Two competing orchestrators (§13 violation today)

1. **`pipeline.scan()`** — folder scanner/watch (`pipeline.py:210-270`, watch loop `:273-287`):
   - CRM docs → `_process_doc` (`:174-207`): `parse.read_table` (`parse.py:140-153`) → `parse.map_headers` alias table (`parse.py:45-81`, confidence gate `LOW_CONFIDENCE = 0.5` at `pipeline.py:20,178`) → `row_to_contact` (`parse.py:174-188`) → `DedupIndex.duplicate_reason` → `db.upsert_contact` into **canonical** `contacts` (`pipeline.py:200`).
   - EML → `_process_eml` (`:116-171`): deterministic fields (`:120-121`) → optional LLM when `cfg["chain"]` non-empty (`:124-129`) → `merge_fields` local-wins (`:131`) → staged `eml_emails` + `eml_contacts` (`:149,161`) → **auto-push to canonical `contacts` with no review gate** (`:164-171`).
2. **`intake.universal_intake()`** — file-path batch API (`intake.py:25-130`), served by `POST /api/intake` (`app.py:136-145`):
   - size/magic/extension checks (`intake.py:42-59`), dead line `adapter = get_adapter if False else None` (`:61`), adapter dispatch (`:62-67`).
   - EML AI branch (`:69-90`) is **latent-broken**: `:78` calls `llm.extract(...)` but `intake.py:10` only imports `parse_json` — the module name `llm` is unbound, so any non-empty `chain` raises `NameError`, caught at `:121` and reported as a file ERROR. Unreachable only because `app.py:144` calls `universal_intake(file_paths)` **without passing `chain`** (default `[]`, `intake.py:25`).
   - Writes straight to **canonical** `contacts` (`intake.py:106`) — no staging, no validation, no `DedupIndex`, and drops `source_row`/`field_origin`/`extraction_run_id`/`whatsapp`/`email_secondary`/`phone_secondary`/`files`/`products_misc` (`:94-105`).
   - Frontend calls it with **bare filenames**, not paths (`static/app.js:114-118` `fileQueue.map(f => f.name)`), so browser-originated intake will fail `file not found` (`intake.py:41`) for any file outside CWD.

**Result:** the same file type is extracted by different code depending on entry point (folder scan vs `/api/intake`), with different mapping logic (`parse.ALIASES` vs adapter substring), different dedup behavior, and different destination tables. This is the §13 "competing orchestrators" condition.

### 1.3 Prompts actually used today

- **The only system prompt:** `llm.SYSTEM_PROMPT` (`llm.py:12-16`) — 10-key single-contact JSON, EML-signature-specific ("You extract one contact and company location from an email signature/header/body"). Identical text in the reference: `[Dev] services/llm_router.py:25-29`. It has **no** `schema_version`, no `companies[]`, no `call_logs[]`, no `field_evidence`, no confidence labels, no source-specific extensions.
- **User prompt wrapping (the good part, reuse as-is):** `build_llm_prompt()` wraps content in `--- BEGIN/END UNTRUSTED EMAIL CONTENT ---` with subject/from/to/date header context (`services/eml_processor.py:262-273`); guarded by tests (`[Dev] tests/test_prompt_injection.py:11-17`; Local has no equivalent test).
- **No `services/prompts/` package exists in either repo** (`ls services/` — Local: adapters, eml_dedup_rules, eml_processor, parser; Developer adds data_access, eml_store, extraction, llm_router, pdf_exporter).
- Prompt assembly is only wired for EML (`pipeline.py:125`, `intake.py:78`, `[Dev] api/eml.py:264`); spreadsheet/PDF/TXT/CSV never send anything to a model (§5 Layer 2 gap-fill is therefore EML-only today).

### 1.4 LLM output validation present today

- `llm.parse_json()` (`llm.py:29-73`): strips fences, JSON or first-`{...}` extraction, list→first-object, per-key length caps (`:48-52`), `null`/`"null"` normalization (`:58-60`), email regex → `None` on failure (`:66-68`), website regex (`:69-71`). **Unknown keys pass through untouched** (`:55-57`) — so an LLM returning `{"id": 999, "created_at": "..."}` is accepted; no `schema_version` check, no type checks on arrays, no per-field evidence check, no call_logs gating. Reference `[Dev] services/llm_router.py:53-99` is the same algorithm (only differences: Local re-imports `re` at `:67`, Developer passes through unknown keys identically at `:80-82`).
- Tests: `tests/test_llm_validation.py` (8 tests: valid/null/oversized/invalid-email/fences/empty/list/redact).
- **No contract validation service exists**; invalid-but-parseable JSON is staged as-is.

### 1.5 Dedup present today

- `db.DedupIndex` (`db.py:345-388`): in-memory sets loaded from a table (`:351-364`), match order **exact email → phone (≥10 digits, substring-containment either direction) → name (any normalized name ≥3 chars)** (`:375-388`). The name rule (`:384-387`) means "Asha Rao" in two unrelated files auto-merges — violates §8 "never assume same name = same person".
- `services/eml_dedup_rules.py`: `normalize_email` `:6-7`, `normalize_phone` `:9-10`, `normalize_name` `:12-15`, `is_duplicate` same email→phone→name priority `:17-34` (name rule `:30-33`), `phone_key` India collapse `:37-47`. **Byte-identical with `[Dev]`** (verified `cmp`).
- **Duplication inside CRM_Local itself:** `db.normalize_email` (`db.py:341-342`) and `db.phone_key` (`db.py:304-311`) re-implement the same two functions — two normalization code paths that can drift.
- Merge semantics: `db.upsert_contact` enriches empty fields only (`db.py:417-424`), falls back `_find` email → raw phone → name+phone (`:391-406`) — note `_find` matches **raw** `phone_primary`, not `phone_key`, so `+91 98765 43210` vs `9876543210` won't match there even though `DedupIndex` would flag it (inconsistent dedup surfaces).
- No scoring tiers (EXACT/PROBABLE/CONFLICT), no conflict preservation, no website/name/company normalization, no CRM-side/staging-side shared engine (staging dedup uses `is_duplicate`, canonical uses `DedupIndex`, upsert uses `_find` — three matchers).

### 1.6 Provenance — mostly NOT populated

- Available: `NormalizedContact.source_file/source_row/extraction_run_id/field_origin/confidence` (`services/adapters/__init__.py:29-33`); `contacts` columns `source_file, source_row, extraction_run_id, field_origin, email_key, phone_key` (`db.py:71-72`); `extraction_runs` table (`db.py:155-161`).
- Populated: only `source_file` (and `source_row` inside the adapter, then dropped) — `intake.py:94-105`; pipeline sets none of them for CRM docs (`pipeline.py:189-201` passes only field values + `source_file` at `:200`) and no `field_origin` for EML (`pipeline.py:131-144`).
- `extraction_runs` has **zero writers** in CRM_Local (grep: only `db.py` declares it). Reference writes it: `[Dev] services/data_access.py` (`create_extraction_run`, used `[Dev] api/intake.py:57-60`).
- **No per-field evidence** (`excerpt`/`location`/`confidence`) exists anywhere in either repo — §6 EVIDENCE REQUIREMENTS is entirely unbuilt.

### 1.7 Where the old EML path coexists with the new adapter path

Three coexisting EML flows (all can run against the same file):

| Path | Entry | Deterministic | AI | Staging | Canonical push |
|---|---|---|---|---|---|
| A. folder scan | `pipeline.scan("eml")` → `_process_eml` (`pipeline.py:116-171`) | `parse_eml_bytes` + `extract_local_fields` | `llm.extract` if chain (`:124-129`) | ✅ `eml_emails` + `eml_contacts` (`:149,161`) | ⚠ auto-push, no review (`:164-171`) |
| B. universal intake | `POST /api/intake` → `intake.universal_intake` (`intake.py:69-90`) | `EmlAdapter` (re-parses file) | ⚠ intended but NameError-broken (`:78`) | ❌ none | ⚠ direct upsert (`:106`) |
| C. reference-only | `[Dev] POST /eml/process` (`[Dev] api/eml.py:219-345`) | same processor | `extract_json` (`:264`) | ✅ Supabase `eml_store` | ⚠ auto-push (`:305-319`) — **not ported; CRM_Local has no `/eml/*` routes** |

Path B re-reads and re-parses the file a second time inside the EML branch (`intake.py:71-75`) after the adapter already parsed it — duplicate work, and the adapter's computed `to/cc/bcc` (`services/adapters/eml.py:22-24`) are discarded because `contact_dict` omits them (`intake.py:94-105`).

### 1.8 Divergences between the two repos' shared services

| File | Status |
|---|---|
| `services/eml_processor.py` | **byte-identical** (`cmp`) |
| `services/eml_dedup_rules.py` | **byte-identical** (`cmp`) — must stay so; do not edit |
| `services/parser.py` | **byte-identical** (`cmp`) |
| `services/adapters/*.py` (7 files) | **byte-identical** (`cmp`) |
| `services/__init__.py` | differs by one comment line only |
| `parse.py` vs `[Dev] api/parse.py` | **materially different**: Local has the full alias/header-mapping engine (`parse.py:18-81`); Developer's is a thin parse endpoint (61 lines, `parse_file` only) |
| `llm.py` vs `[Dev] services/llm_router.py` | **materially different**: retry policy Local `[1,2]` w/ 3 attempts (`llm.py:9,155-165`) vs Developer 1 attempt + 45 s deadline (`llm_router.py:10,139-175`); Local creates a fresh `httpx.AsyncClient` per call (`llm.py:134-136`) vs shared client (`llm_router.py:45-51`); Developer adds a 500-entry response cache (`llm_router.py:40-51,166-169`) Local lacks; system prompt text identical; `parse_json` algorithm identical |
| Provider list | Local `PROVIDERS` list incl. `ollama` (`llm.py:26`); Developer `PROVIDERS` dict has `gemini: None` placeholder (`llm_router.py:31-38`) and handles ollama only implicitly — Local's ollama path (`llm.py:82-92`) is ahead of the reference |

### 1.9 Validation, staging, provider-manager reality check (§7/§12)

- **Validation:** only `parse.clean_email`/`parse.clean_phone` (`parse.py:156-171`), `llm.parse_json` field caps (`llm.py:47-73`), and (reference only) `validate_email`/`classify_phone` `[Dev] api/contacts.py:58-76` — **not present in CRM_Local**. The seven issue categories (`INVALID, SUSPICIOUS, MISSING, UNCERTAIN, FIELD_MAPPING_ERROR, POSSIBLE_DUPLICATE, CONFLICT`) appear in **no source file** in either repo (grep confirmed). None of the three §7 example strings is handled anywhere.
- **Staging:** only `eml_contacts` (dedup_status + pushed_to_crm, `db.py:132-142`); no review statuses, no import statuses, no `Review First / Smart Import / Always Stage` policy anywhere (grep: zero hits in both repos' code).
- **Provider manager:** config-file `chain` list (`config.py:13`), wholesale `POST /api/config` (`app.py:115-125`), `POST /api/test-llm` → `llm.test_entry` (`app.py:253-256`, `llm.py:169-176`), enable/disable via `entry.enabled` (`llm.py:149`), reorder = array order, model = free text (`app.py:54-59`), base URL only consumed for ollama (`llm.py:83`), global timeout/retry not per-entry (`llm.py:9-10`).
- **§12 secret violation (both repos):** `GET /api/config` returns the whole config **including `chain[].api_key`** (`app.py:106-112`), and the browser reads it (`static/app.js:305,312,327-339` — `addProvider()` even round-trips the key through `prompt()` at `:326`). Same in reference: `[Dev] api/settings.py:47-48` returns `_settings` with keys. Secrets are therefore exposed to browser JS today.
- **External-transmission awareness:** none. Empty chain = local-only by comment (`config.py:11-13`), but there is no mode flag, no UI indicator, no explicit user-visible notice when a file's text leaves the machine.

---

## 2. Target architecture

### 2.1 Module layout (new files marked ✨, existing kept marked)

```
CRM_Local/
  intake.py                  # THIN: HTTP entry only — validate request, call orchestrator, return report
  pipeline.py                # THIN: folder scan/watch loop → calls orchestrator per file (keeps RunState, ledger)
  llm.py                     # transport only (providers, retry, parse_json → moved out)
  parse.py                   # kept: header alias engine + table readers (single source for tables)
  db.py                      # kept: schema + repositories (no dedup logic left here)
  services/
    adapters/                # kept, extended: return source metadata (sheet/page/row/headers) not just contacts
    prompts/                 ✨ NEW
      contact_extraction.py  # MASTER_SYSTEM_PROMPT (§6 verbatim) + SOURCE_EXTENSIONS + build_messages()
    contract.py              ✨ NEW — validate_extraction_payload() (backend contract gate)
    validation.py            ✨ NEW — one unified validator (§7)
    dedup.py                 ✨ NEW — one dedup engine (§8); imports normalization from eml_dedup_rules (untouched)
    providers.py             ✨ NEW — provider manager (§12), secrets server-side
    orchestrator.py          ✨ NEW — the ONE pipeline (intake→classify→adapter→L1→L2→normalize→validate→dedup→stage)
    eml_processor.py         # kept byte-identical with [Dev] (do not edit)
    eml_dedup_rules.py       # kept byte-identical with [Dev] (do not edit) — normalization core for services/dedup.py
    parser.py                # kept byte-identical with [Dev] (do not edit)
```

### 2.2 Pipeline stages and owning file

| # | Stage | Owner | Built from (existing code) |
|---|---|---|---|
| 1 | **intake** — size/magic/extension/encoding checks, assign `source_file` | `services/orchestrator.py` | `intake.py:36-59` (moves), fixes `:61` dead code |
| 2 | **classify** — does this file hold contacts / companies / emails / call records / products / other? deterministic pre-checks first (has `@`, has phone-shaped values, has table, has MIME headers), optional AI classification second | `services/orchestrator.py` | new; gate = §5 General |
| 3 | **adapter** — format parse returning *records + source metadata* (sheet name, page numbers, original headers, row numbers, raw cell values) | `services/adapters/*` + `parse.py` | extend `ExtractionResult` with `source_meta`; unify `csv.py` onto `parse.parse_csv` (delimiter sniff) |
| 4 | **Layer 1 deterministic** — header/alias map, regex families, MIME headers, signature block, phone/email/pincode normalization, address/city recognition | `parse.py` + `services/eml_processor.py` (unchanged) | always runs, offline |
| 5 | **Layer 2 optional AI** — only for fields still `None`/`UNCERTAIN`, only if provider configured | `services/orchestrator.py` + `llm.py` + `services/prompts/contact_extraction.py` | `merge_fields` local-wins (`eml_processor.py:275-287`) generalized to every source |
| 6 | **normalize** — canonical keys (`email_key`, `phone_key`, name/company/website normalization) | `services/dedup.py` | absorbs `db.py:304-342` duplicates |
| 7 | **validate** — §7 field rules → issue list per record | `services/validation.py` | new (ports `parse.clean_*`, Developer `classify_phone/validate_email`) |
| 8 | **dedup** — match priority + scoring against staging AND canonical | `services/dedup.py` | merges `DedupIndex`, `eml_dedup_rules.is_duplicate`, `db._find` |
| 9 | **stage** — write staging row + raw record + evidence + provenance; **never** canonical | `services/orchestrator.py` → `db.py` | new tables/extended `eml_contacts` (see 2.3) |

### 2.3 What gets deleted / merged for "one orchestrator, one validator, one dedup engine"

| Today | Action |
|---|---|
| `intake.universal_intake` extraction+upsert body (`intake.py:61-120`) | **delete** → replaced by `orchestrator.process_file()`; `intake.py` keeps only request validation + response shaping |
| `pipeline._process_doc` / `_process_eml` extraction bodies (`pipeline.py:116-207`) | **delete** → both call `orchestrator.process_file()`; `pipeline.py` keeps scan/watch/ledger/RunState |
| adapter-internal substring mapping (4× duplicated: `xlsx.py:29-47`, `xls.py:25-45`, `csv.py:23-43`, `pdf.py:24-45`) | **delete** → adapters return raw rows + headers; mapping lives once in `parse.map_headers`/`ALIASES` |
| `parse.clean_email/clean_phone` | **move** into `services/validation.py` |
| `llm.parse_json` field checks (`llm.py:47-73`) | **split**: JSON extraction stays in `llm.py`; field/type/contract validation → `services/contract.py` |
| `db.DedupIndex` + `db._find` + `db.phone_key` + `db.normalize_email` (`db.py:304-440`) | **delete logic** → `services/dedup.py` (db.py keeps SQL only) |
| `services/eml_dedup_rules.py` | **untouched** (byte-identical constraint) — imported as the normalization core |
| `pipeline` auto-push (`pipeline.py:164-171`) + `intake` direct canonical upsert (`intake.py:106`) | **delete** → staging only; canonical write happens exclusively at review/approval (Phase 2 import policies) |
| `llm.SYSTEM_PROMPT` (`llm.py:12-16`) | **delete** → replaced by `services/prompts/contact_extraction.py` |
| `eml_emails`/`eml_contacts` as the only staging | generalize: one `staged_records`/`staged_contacts` model with `source_type` (EML subset keeps its columns for the Emails view) |

**Net effect:** `POST /api/intake` and folder scan become two *front doors* onto the same `orchestrator.process_file()`; validation and dedup each exist once; `eml_processor`/`eml_dedup_rules`/`parser` stay byte-identical to the reference.

---

## 3. Prompt + contract integration (§6)

### 3.1 Assembly

`services/prompts/contact_extraction.py`:

```python
MASTER_SYSTEM_PROMPT = """<§6 text verbatim, ABSOLUTE RULES … FINAL OUTPUT>"""

SOURCE_EXTENSIONS = {"spreadsheet": …, "pdf": …, "csv": …, "txt": …, "eml": …}   # §5 source blocks

def build_messages(source_type: str, layer1_summary: dict, schema: dict) -> list[dict]:
    system = MASTER_SYSTEM_PROMPT + "\n\nSOURCE-SPECIFIC EXTENSIONS (" + source_type + "):\n" + SOURCE_EXTENSIONS[source_type]
    user = ("<EXTRACTION REQUEST>\nschema_version: crm-extraction.v1\nsource_type: …\n"
            "DETERMINISTIC LAYER-1 FINDINGS (authoritative, do not overwrite):\n…\n"
            "--- BEGIN UNTRUSTED SOURCE CONTENT ---\n<content>\n--- END UNTRUSTED SOURCE CONTENT ---")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
```

- **One** master prompt, **one** JSON contract, source-specific *extensions* concatenated per §6 (never separate contradictory prompts).
- Untrusted wrapping reuses the proven `build_llm_prompt` pattern (`services/eml_processor.py:262-273`) for **all** sources, not just EML.
- Layer-1 summary is included so the model sees what is already populated and can gap-fill only (rule reinforcement, plus `merge_fields` enforces it in code).
- LLM is invoked **only** when: provider configured (`config.chain` non-empty) AND classify stage says AI is useful AND at least one target field is unresolved.

### 3.2 Contract enforcement on the backend (`services/contract.py`)

Gate runs on every model response **before staging**:

1. `json.loads` success (via `llm.parse_json` extraction only) — else reject.
2. `payload["schema_version"] == "crm-extraction.v1"` — else reject.
3. `payload["source_type"] == expected` — else reject.
4. Top-level keys exactly `schema_version, source_type, companies, contacts, emails, call_logs, unmapped_fields, warnings` — **no extra keys** (§6 "Never add unsupported keys"): extra → reject (this is what stops LLM-generated `id`/`created_at`/`session_id`).
5. Type checks: `companies/contacts/emails/call_logs/unmapped_fields/warnings` are arrays; scalars are `str | null`; `has_signature` is `bool`; `contact_indices` array of ints **indices into the response's own contacts array** (never DB IDs).
6. Null/empty rules: unknown scalar → `null` (normalize `"null"`/`""` → `null`), absent collection → `[]`.
7. **Evidence rule:** every non-null scalar in `contacts[]`/`companies[]` must have `field_evidence[key] = {excerpt: str, location: str, confidence in {high,medium,low}}` — missing → that field is *stripped* to `null` (value not trusted), and a warning is appended; `confidence == "high"` on an ambiguous mapping → downgrade to `medium` + warning.
8. **MIME-metadata-wins:** for `emails[]`, deterministic MIME values from `parse_eml_bytes` (`eml_processor.py:155-169`) overwrite the model's `subject/date/sender_*/to/cc/bcc/body_text/has_signature` — the model's copies are discarded, not merged (§6 C).
9. **call_logs gating:** if deterministic classify says the source has no structured call columns, `call_logs` must be `[]`; non-empty → drop the array + `CONFLICT` warning.
10. Field-level format pre-checks delegated to `services/validation.py` (email/phone/pincode/name/company rules) — invalid values are nulled in the *staged* copy, raw model output retained in provenance JSON.

### 3.3 Rejection path

`contract.validate()` returns `(payload | None, issues[])`.
- `None` → **nothing from AI is staged**: the record proceeds as Layer-1-only, `warnings += ["ai_output_rejected: <reasons>"]`, run counted `ai_rejected`. Never canonical, never partially applied.
- Issues but parseable → strip offending fields, stage remainder with `UNCERTAIN`/`FIELD_MAPPING_ERROR` flags.
- Raw model response stored (truncated) in the run's provenance for audit; API keys never included (reuses `_redact`, `llm.py:142-144`).

---

## 4. Provider manager spec (§12)

### 4.1 Data model (server-side, `config.json` or new `providers.json` in `data_dir()` — `config.py:24-31`)

```json
{ "providers": [ { "id": "p1", "provider": "openrouter", "model": "…", "base_url": null,
    "secret_ref": "env:OPENROUTER_API_KEY | file:<name>", "enabled": true, "order": 0,
    "timeout_s": 120, "max_retries": 3, "last_test": {"at": "…", "ok": true, "detail": "ok"} } ],
  "mode": "local_only | ai_enrichment",
  "import_policy": "review_first | smart_import | always_stage" }
```

- Secrets live in a **separate 0600 file** (or OS keyring when available); `providers.json` stores only `secret_ref`. Today's keys-in-config (`config.py:11-13`) are migrated out.
- Matches existing chain semantics: ordered failover (`llm.extract`, `llm.py:147-166`), `enabled` flag (`:149`), `base_url` for ollama (`:83`), per-entry `timeout`/`retries` replace globals (`llm.py:9-10`).

### 4.2 API surface (extends `app.py`; replaces wholesale config writes for chain)

| Endpoint | Purpose |
|---|---|
| `GET /api/providers` | list — **masked**: `{"id","provider","model","base_url","enabled","order","has_key":true,"last_test"}` — never `api_key` |
| `POST /api/providers` | add |
| `PATCH /api/providers/{id}` | edit model/base_url/timeout/retries/secret (secret write-only field) |
| `DELETE /api/providers/{id}` | remove |
| `POST /api/providers/{id}/enable` · `/disable` | toggle |
| `PUT /api/providers/order` | reorder |
| `POST /api/providers/{id}/test` | `llm.test_entry` (`llm.py:169-176`) |
| `GET /api/settings/mode` · `PUT` | `local_only` / `ai_enrichment` + `import_policy` |

`GET /api/config` must stop returning `chain` secrets (`app.py:106-112`); `static/app.js:305-339` updated to the masked endpoints (frontend change flagged for the frontend owner — this doc is read-only).

### 4.3 Secrets stay server-side

Key never rendered to JS (masked `has_key`), never logged (`_redact`, `llm.py:142-144`), never inside `extraction_runs.config_snapshot` (mask at write). File perms 0600 under `data_dir()`.

### 4.4 "External request in progress" awareness

- Every Layer-2 call sets an in-flight counter exposed as `GET /api/status` → `external_requests_in_progress: n` (extend existing status route `app.py:90-103`); the UI shows a persistent banner while `n > 0` and for `mode = ai_enrichment` at all times.
- Pre-flight: before the first external call of a session, if `mode == ai_enrichment` and no explicit acknowledgement recorded → refuse with `{"error": "external_transmission_not_acknowledged"}`.
- No external request may be issued when `mode == local_only`, regardless of `chain` contents (today an empty-chain comment is the only guard, `config.py:11-13`).

---

## 5. Validation service spec (§7)

**Single module** `services/validation.py`; runs **post-extraction (Layer1+Layer2 merge), pre-staging**, on every record from every adapter — one validator for all six formats and both layers (§13).

### 5.1 Field rules

| Field | Rules | Notes |
|---|---|---|
| email | RFC-ish syntax (`parse.clean_email` regex, `parse.py:10,156-158`); artefact patterns → `SUSPICIOUS`: `*.png@`, `*.jpg@`, embedded `imageNNN` localparts, `filename.ext@` domains; never reject for unfamiliar TLD (H8) | `INVALID` only on syntax failure; suspicious values staged **and flagged**, never dropped |
| phone | digits-only key via `phone_key` (`eml_dedup_rules.py:37-47`); classify mobile (IN `[6-9]\d{9}`), landline/STD (with/without leading 0 + code), international `+<cc>` explicit; `phone_country` set only from explicit prefix; label evidence for WhatsApp | never assume mobile; never invent cc; keep raw string |
| pincode | IN: 6 digits, first digit 1–9 (`parser.py:172`); non-IN 5-digit ZIP only when source country evidenced; otherwise `UNCERTAIN` | never invent |
| website | domain syntax, strip scheme for key, reject if it is actually an email (existing blanking, `eml_processor.py:186`) | |
| name | ≥2 tokens, ≤80 chars, reject sentence-shaped (ends `.` with >6 tokens, greeting verbs, contains `@`) → `SUSPICIOUS`; reuse/extend `NAME_REJECT` (`eml_processor.py:50-55`) | `share the quotation asap.` → SUSPICIOUS |
| company | reject measurement/spec-shaped strings (`\d+\s*(FT|Inc|MM|Inch|Borewell|Pipeline|Size)` etc.) → `SUSPICIOUS`; reject role-title-shaped → `FIELD_MAPPING_ERROR` | `Depth.- 900 FT. Borewell Pipeline Size.- 2.5 Inc` → SUSPICIOUS (flagged, retained) |
| address/city | city must appear in source evidence, not derived from company name; else `UNCERTAIN` | |
| designation/industry | cross-check H1: role-keyword string in `industry` → `FIELD_MAPPING_ERROR`; industry-keyword string in `position` → flag | |

### 5.2 Issue categories → record linkage

`INVALID | SUSPICIOUS | MISSING | UNCERTAIN | FIELD_MAPPING_ERROR | POSSIBLE_DUPLICATE | CONFLICT`, each as
`{record_ref, field, category, detail, raw_value}` appended to the staged row's `validation_issues` JSON (new column) **and** surfaced as `warnings[]` in the intake report (`intake.py:118` already returns `warnings`). `MISSING` = required-without-evidence (e.g. no email **and** no phone → row not stageable as contact, preserved as raw record).

**Hard rule:** validation never deletes the raw source value — raw row is always archived in `records` (§F of the matrix), flagged values stay in `raw_value`.

---

## 6. Dedup engine spec (§8)

**Single module** `services/dedup.py`, used by staging **and** canonical import (today: three matchers, §1.5).

### 6.1 Normalization (imports `eml_dedup_rules` unchanged)

| Key | Function | Source |
|---|---|---|
| `email_key` | trim + lower | `eml_dedup_rules.normalize_email:6-7` |
| `phone_key` | digits-only, strip `91` from 12-digit, `0` from 11-digit, ≥7 else None | `eml_dedup_rules.phone_key:37-47` |
| `name_key` | lower + collapse whitespace + strip punctuation/honorifics | extends `normalize_name:12-15` |
| `company_key` | lower, strip legal suffixes (`pvt ltd, limited, llp, inc…`) | new |
| `website_key` | lower, strip `scheme/www/trailing slash` | new |

### 6.2 Match priority (in order, first hit wins the *tier*)

1. **EXACT** — equal `email_key`, or equal `phone_key` with ≥10 digits (containment rule retained from `DedupIndex.duplicate_reason:379-383` for `+91` variance).
2. **PROBABLE (strong composite)** — same `name_key` **and** (`company_key` equal or `phone_key` matches) → score ≥ 0.9.
3. **PROBABLE (name+company)** — `name_key` + `company_key` both equal, no contradicting email/phone.
4. **CONFLICT** — same `email_key` but different `name_key`, or same `phone_key` with different `email_key`+`name_key` → flagged for human resolution, **never merged**.
5. **FUZZY** — token-set similarity on `name_key` ≥ 0.85 or company fuzzy ≥ 0.9 → staged as `POSSIBLE_DUPLICATE`, human review only.

### 6.3 Outcomes

- EXACT → `dedup_status = EXACT_DUPLICATE`; auto-*link* (point staging row at existing record), never auto-overwrite; enrich-empty-only semantics preserved (`db.upsert_contact` rule, `db.py:417-424`, becomes the import-time merge rule).
- PROBABLE → `PROBABLE_DUPLICATE` → Review Queue.
- CONFLICT → `CONFLICT` + `warnings`; both values retained (§6 "Preserve conflicting values for human review").
- Name alone **never** matches (removes `DedupIndex` name rule `db.py:384-387` and `is_duplicate` name rule `eml_dedup_rules.py:30-33` from *auto* merge — the shared module keeps its function for compatibility but the engine gates it behind composite scoring).
- Merge preserves: emails (primary+secondary), source files (append list), call logs, company relationships, notes, import history, provenance (`field_origin`, evidence) — modeled on reference merge `[Dev] api/eml.py:53-160` and `[Dev] services/data_access.py:125-162`, extended with file-list + evidence retention.

---

## 7. Test plan

### 7.1 Unit (fast, no network — extend existing suites: 58 tests today)

| Area | Tests | Anchor |
|---|---|---|
| validators | each §7 example: `image001.png@01dd4100.ede` → SUSPICIOUS; `share the quotation asap.` → SUSPICIOUS-as-name; `Depth.- 900 FT. Borewell Pipeline Size.- 2.5 Inc` → SUSPICIOUS-as-company; IN mobile/landline/INTL classify; pincode IN/non-IN; unfamiliar-domain email accepted | new `tests/test_validation.py` |
| normalizers | `phone_key` `+91/0/landline` variance, `email_key`, `company_key` suffix strip, `website_key` | extend `tests/test_dedup_rules.py` (4 tests) |
| contract checker | reject: missing `schema_version`, extra key (`id`, `created_at`), wrong `source_type`, array type errors, missing `field_evidence` on populated field, non-empty `call_logs` on ungated source, MIME-vs-AI metadata conflict | new `tests/test_contract.py` |
| prompt assembly | §6 master text present verbatim; exactly one source extension concatenated; untrusted delimiters present; no API key in messages | new `tests/test_prompt_assembly.py` |
| dedup tiers | EXACT email/phone; PROBABLE name+company; CONFLICT same-email-different-name; name-only → no auto-merge; fuzzy → review | extend `tests/test_dedup_rules.py` |
| orchestrator | single path: `/api/intake` and `scan()` produce identical staged rows for same file (kills the two-orchestrator split) | new, extends `tests/test_intake.py` (3 tests) + `tests/test_pipeline.py` (5) |

### 7.2 Integration — one fixture per format (all six)

`tests/fixtures/{contacts.xlsx, multi_sheet.xlsx, contacts.csv, report.pdf, phones.txt, signature.eml}` → assert: staged row count, source metadata (sheet/page/row), evidence present per populated field, `validation_issues` populated for planted bad values, **no canonical write** without approval, provenance columns set (`extraction_run_id`, `field_origin`). EML fixture additionally asserts MIME metadata wins over AI and prompt-injection payload in body is treated as data (port `[Dev] tests/test_prompt_injection.py`).

### 7.3 Accuracy checks

- **No-invention:** golden set where N fields must stay `null`; any non-null without evidence excerpt = fail.
- **No-false-contact:** TXT prose fixture must yield 0 contacts; EML mentioning 3 names with 1 signature must yield exactly the evidenced contact(s) with roles labeled (§5 EML).
- **Local-wins:** fixture where Layer-1 and Layer-2 disagree → staged value equals Layer-1, AI alternative stored as proposed alternative.
- **Offline:** with `mode=local_only` and network blocked, all six fixtures still extract (Layer 1 only).

### 7.4 Mapping to brief acceptance scenarios A–G

> **SUPERSEDED (D-024, 2026-11-07):** the verbatim A–G scenario text now exists at `docs/ACCEPTANCE_SCENARIOS.md`, and the authoritative 57-step traceability matrix lives in `docs/QA_ACCEPTANCE_PLAN.md`. The mapping below is provisional — re-check it against those two files before relying on it.

The A–G scenario text is **not in either repo** (only `TEAM_BOARD.md:49` references it for the QA engineer), so this mapping is provisional and must be re-checked against the brief text:

| Scenario (provisional reading) | Covered by |
|---|---|
| A — drop a mixed folder → all six formats extracted | §7.2 integration fixtures + orchestrator single-path test |
| B — offline deterministic extraction with no provider | §7.3 offline check; `local_only` mode test |
| C — AI enrichment fills gaps only, never overwrites | local-wins accuracy check + contract evidence tests |
| D — no invented values / no false contacts | no-invention + no-false-contact accuracy checks |
| E — dedup without wrong auto-merges | §7.1 dedup tier tests (name-only must not merge) |
| F — validation flags the §7 examples | §7.1 validator tests (three exact strings) |
| G — secrets never in browser JS / external transmission aware | provider-manager tests: masked `GET`, 0600 file, banner state, `local_only` blocks calls |

---

## 8. Open questions (10)

1. **Staging schema:** keep `eml_contacts` as *the* staging table with extra columns, or introduce a unified `staged_records` table (with `source_type`) and keep `eml_contacts` as an EML-specific view? (Affects §C of the matrix and Phase 2 DB work.)
2. **`contact_indices` semantics:** should the contract's `emails[].contact_indices` also be required for spreadsheet/PDF multi-contact rows (row → contact index), or is evidence `location` enough there?
3. **Where does `receiver_name/receiver_email` live?** `eml_emails` lacks the columns (`db.py:121-128`) though §6 C requires them — add columns, or derive at read time from `to_emails`?
4. **Canonical write moment:** with §12 import policies (Review First / Smart Import / Always Stage), does `pipeline`'s auto-push (`pipeline.py:164-171`) get deleted outright in Phase 2, or retained only for `always_stage`-off modes?
5. **25-type mapping server-side or client-side:** the reference does detection in the browser (`[Dev] frontend/app.js:100-158`). Should CRM_Local port `detectField` to the backend (needed for evidence + staging `mapping`), keeping the UI purely confirmatory?
6. **Keyword→Designation conflict:** the reference maps mapping-type `keyword` to the Designation column (`[Dev] frontend/app.js:604`) while `parse.py:33` maps `keyword`-like headers elsewhere — which is authoritative for CRM_Local?
7. **Acceptance scenarios A–G:** exact text needed from the master brief to finalize §7.4 (not present in either repo).
8. **Call logs source:** does any expected input format (CSV/XLS columns like `call_date`, or a dedicated call-export CSV) exist as fixtures? §6 D gating is clear, but test data shape is unknown.
9. **AI layer for non-EML sources:** budget/latency policy for Layer 2 on a 50-file spreadsheet batch (reference uses a 45 s deadline, `[Dev] api/intake.py:64`) — per-file deadline, per-batch budget, or user-configurable via provider manager `timeout_s`?
10. **`phone_secondary` multi-value:** canonical `contacts.phone_secondary` is a single TEXT (`db.py:67`) while staging may hold lists (reference truncates to first value, `[Dev] api/eml.py:44-49`) — confirm list-in-staging / first-value-in-canonical, or schema change to store all?
