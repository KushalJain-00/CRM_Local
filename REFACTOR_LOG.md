# Untangle Refactor — Decision Log

Branch `refactor/untangle` (worktree off `a57e3c8`). User WIP on
`feat/prompt-intelligence` untouched. Each phase ends with a green test run.

Baseline at `a57e3c8`: **356 passed, 1 xfailed** (`pytest -q`).

## D-U1 (Phase 1): one authoritative identity-key module = `services/keys.py`

- `normalize_email` = `strip().lower()` (was identical in 3 places).
- `normalize_phone` = digits-only, no length rule (used by `is_duplicate`).
- `phone_key` = digits-only; collapse 12-digit `91` prefix and 11-digit `0`
  trunk; `None` if <7 digits (G14). One implementation.
- `name_key` = lower, strip honorifics (`mr mrs ms dr prof shri smt`), drop
  `.,'"`-`, collapse whitespace. **This semantics wins** — it is what
  staging/approval/contacts-edit paths already write, and `test_dedup.py`
  pins it. The §6.5 doc comment (`lower(collapse_ws(v))`) and `db.py`'s raw
  copy were the outliers; doc updated to match. Existing prod rows written
  by v6 backfill with raw keys are NOT rewritten implicitly — possible owner
  decision: explicit `v11` re-backfill migration (not applied in this
  refactor).
- `company_key` = legal-token-stripped composite from `services/dedup.py`
  (was the only implementation; `db.upsert_contact` skipped it entirely).
- `website_key` = scheme/`www.`/path-stripped host from `services/dedup.py`.
- `record_keys(record)` returns all five keys (the `_keys`/`chunking`/
  inline-api copies deleted).
- `identity_key(record)` = the `("e",email) | ("p",phone) | ("n",name,company)`
  priority tuple shared by staging batch-dedup and chunking merge keys.
- `is_duplicate(...)` is re-implemented on top of `normalize_email` /
  `phone_key` / `normalize_name` (plain collapse kept ONLY here —
  `is_duplicate` is the pre-engine API used by docs G14; kept because the
  approved stop list does not remove it).
- `services/dedup.py` keeps the band-comparison engine (`compare`,
  `find_matches`, `EXACT_DUPLICATE`…) and imports keys from `keys.py`.
- `eml_dedup_rules.py` deleted; all importers updated to `services.keys`
  or `services.dedup`.
- `db.py`: `name_key`, `website_key`, `phone_key`, `normalize_email`,
  `email_key` deleted — importers moved to `services.keys`. The v6 backfill
  now calls the shared normalizers (identical output on fresh DBs).
- All writers generate complete keys via `record_keys`:
  staging insert, staged→contacts approval, contacts edit, chunking.

Migration impact: none applied. v6 code changed only in which helper it
calls; already-migrated prod DBs are unaffected. Tests pinning honorific
stripping (`test_dedup.py`) stay green; tests pinning old raw `db.name_key`
were updated to the authoritative semantics (none existed — v6 test uses
"Alice").

## D-U2 (Phase 1 testing): behaviour equivalence guard

`tests/test_keys.py` pins: honorific/punctuation/whitespace/case,
`+91`/`0`/12-digit phones, email trim/case, missing fields, priority
tuple, and identity-db-write consistency across staging→approval paths.

## D-U1b (Phase 1, done): divergence fix + coverage

- `db.py`: dropped local `name_key`/`website_key`/`phone_key`/`normalize_email`;
  imports shared keys. v6 backfill now uses `company_key` for company
  (was `name_key` — company rows were getting unstripped keys).
- `insert_eml_contact` likewise uses `company_key` for company_key (was `name_key`).
- `api/staged.py`: `_canon_keys` → `record_keys(dict(sc))` (stored-key-wins
  fallback removed); approval phone/email normalize via shared `phone_key` /
  `normalize_email`; `dedup-check` endpoint uses shared normalizers; the
  name+phone hint keeps `LIKE` semantics on `normalize_name` output.
- `api/contacts.py`: edit endpoint recomputes keys through `record_keys`
  (one call), sets only the key columns whose source field was edited,
  keeps the unmigrated-column probe.
- `services/eml_dedup_rules.py` deleted; imports moved to `services.keys`.
- New `tests/test_keys.py` (39 tests): honorifics/punctuation/ws/case,
  India phone variance, email case/trim, `record_keys` on missing fields,
  priority tuple, .eml-vs-.csv identity agreement, staged/canonical key
  consistency, honorific-variant canonical dedup, `is_duplicate`.
- Full suite: **395 passed, 1 xfailed** (baseline 356 + 39 new).

## D-U2 (Phase 2, done): one shared extraction lifecycle = services/extract.py

`process_source()` owns the whole lifecycle: adapter parse → deterministic
Layer-1 → optional contract-validated AI → normalized contacts → staging →
email row (+links) → ledger (`mark_processed`, absolute path). Both entry
points are thin:

- intake.py = data-dir migration of wrapper: spool/limits/bare-name
  resolution + batch assembly + extraction_run + per-file error capture.
- pipeline.py = folder walk/sort/pending-ledger + RunState reporting +
  watcher. `_process_eml`/`_process_doc`/`_ai_document_assist` deleted.

Design rulings (flagged to user in final report):

- **Deterministic never discarded.** Pipeline previously dropped
  deterministic rows when LLM-assist ran (low-confidence files); both paths
  now always stage deterministic rows and *append* contract-validated AI
  rows (the ai_assist "gap-fill" contract). Intake behaviour wins.
- **EML with no identity stages as NEEDS_REVIEW** (D-006/D-007 "never
  dropped"), instead of the scan's silent skip (email row only).
- **Ledger key = absolute path** for both paths (was: basename for intake,
  full path for scan → cross-path double counting).
- **to_emails/cc_emails/bcc_emails now persist for intake-sourced EML**
  (they were dropped by the upload path; kept on the scan path).
  `NormalizedContact` gained the three columns to carry them.
- **Recipients normalized empty-string → NULL** on all paths.
- **EML parsed once** — EmlAdapter stashes `parsed` on ExtractionResult;
  the core reuses it for the email row and the LLM prompt.
- **LLM-skip degradation warning** ("LLM skipped (…) — local fields only")
  is appended in both paths when chain present but extraction failed
  (previously only the scan logged it).
- One explicit conversion boundary in `services/adapters/__init__.py`:
  `eml_to_normalized` / `contract_to_normalized` (table-driven
  `_CONTACT_MAP`). All field-by-field copies and the `_ai_of` hack gone.
- `parse.py` moved to `services/parse.py` (tests import path updated).

Equivalence evidence (original intake vs new, identical input files):
table_good.csv and sparse.csv staging rows byte-identical; eml_basic
differs ONLY by preserved to/cc/bcc (bug fix); eml_no_identity identical
after the NULL normalization above. New `tests/test_extract_parity.py`
(orchestrator-level parity, deterministic/offline) is committed.

Suite: **399 passed, 1 xfailed** (356 base + 39 new keys + 4 parity).

## D-U3 (Phase 3, done): shared infrastructure

- **Limits**: `services/limits.py` (MAX_FILE_SIZE, MAX_TOTAL_SIZE,
  MAX_FILE_COUNT). intake dropped its private copies; pipeline's
  MAX_SCAN_SIZE alias deleted (oversized pre-filter now uses MAX_FILE_SIZE);
  api/intake derives MAX_* from limits; magic-byte gate moved into the xls/
  pdf adapters (`check_signature`, raises before parse) — exact message and
  hard-ERROR intake semantics preserved; api's stale `sys.path.insert` hack
  deleted.
- **Data directory**: app.py's copy deleted — `config.data_dir()` is the
  single implementation. `db._live_db_file` delegates to config.
  **Notable**: `config.data_dir()` is monkeypatchable by tests, but the
  D-030 migration gate must anchor on the *canonical* path. config.py now
  owns both resolvers (`data_dir()` configurable, `canonical_db_path()`
  not; no mkdir) — all path logic in one module. One test
  (test_live_db_file_is_canonical_home_path) caught the naive unification.
- **Connections**: db.connect is the only connection factory (3 identical
  defs collapsed; unused `_sqlite3` and compat lambdas gone). API
  `_get_con()` copies in contacts/staged/emails/history/companies → db.connect()
  (WAL+FK+Row everywhere, closing the FK gap on emails/history/companies-).
  Row-factory transaction semantics unchanged. The unified DB keeps `which`
  as an ignored parameter (tests pass "eml").
- **Reliability spec**: defaults + bounds + descriptions now live together in
  `llm.py` (`default_reliability`, `RELIABILITY_FIELDS`,
  `RELIABILITY_DESCRIPTIONS`); api/settings derives from them; stale inline
  `import llm`s removed. New `tests/test_reliability_config.py` pins the
  contract (8 passed).
- Suite: **407 passed, 1 xfailed**.

Behaviour notes for report: api emails/history/companies now enforce the
same FK pragma as the rest of the app (previously silently off there).

## D-U4 (Phase 4, done): verified surplus removed

Dependency analysis (grep, then AST-based unused-import scan) backed every
removal. No production callers anywhere outside the removed code itself.

Removed dead interfaces (db.py):
- `upsert_contact` (only tests), `insert_eml_contact` (only tests),
  `mark_pushed` (zero refs), `_find` (only upsert), `DedupIndex` (write-only
  in production: pipeline loaded + added, nobody read; duplicate_reason
  test-only), `list_contacts`/`get_contact`/`update_contact`/`delete_contact`
  (api/contacts does its own SQL).
- Removed exclusively-covering tests: test_db.py::test_upsert_enriches_…,
  test_db.py::test_dedup_index_matches_email_phone_and_name,
  test_dedup_rules.py::test_dedup_index_load_and_match
  (407 → 404 passed; no other coverage touched).

- llm.py: `PROVIDERS` compat alias (api/system reads providers.PROVIDERS
  directly), `SYSTEM_PROMPT` vestigial global, `describe_failure` (unused
  params, zero callers). app.py post-mortem comment trimmed to fact.
- Removed all unused imports project-wide (AST scan; re-export modules
  `api/__init__.py`, `services/prompts/__init__.py`, adapters' side-effect
  imports kept by design). Braces-commented from-import in dedup.py fixed by
  hand after the automated pass.
- Suite 404 passed (down 3 = dead-code tests), contract audit identical to
  baseline. Frontend untouched.
