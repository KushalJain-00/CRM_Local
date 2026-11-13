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

## D-U5 (Phase 5, done): frontend consolidation (static/app.js, boot.js, index.html)

Behaviour preserved; onclick global contract and tools/contract_audit.py
lists unchanged (audit identical modulo API-URL listing: '/api/prompts' →
'/api/prompts/contact'+'/api/prompts/eml', added '/api/staged-contacts/bulk-action').

- One API client (`apiRequest`) with a real wait queue (7th caller waits
  instead of throwing); `api`/`apiFormData` kept as function declarations
  (audit contract).
- One badge factory (`badgeFor` + BADGES/BADGE_DEFAULTS tables) for review /
  dedup / import / file vocabularies; stagedBadge consumes it; `isOkStatus`
  replaces 4 identical uppercase checks.
- One view dispatch: `VIEW_LOADERS` shared by swapView + refreshData;
  `VIEW_ICONS`/`VIEW_TITLES` are the single label/icon lists (palette derives
  from them).
- One pagination path (existing renderPagination kept); one error-row helper
  (`tableErrorRow`) used at all 4 sites; sort toggle unified (`toggleSort`),
  contacts switched to the shared `{key,dir}` object; comparator shared.
- One contact-email accessor (`contactEmail`) applied at the 8 fallback sites;
  one `profileHeaderHTML` for the 3 profile-header sites; one `contactEmail`
  for exports; one `compareValues`.
- Density: boot.js keeps only theme/sidebar pre-paint restore; app.js owns
  global + per-table density init — per-table preferences now actually apply
  on load (were saved but never restored).
- Declared implicit global `reliabilityWorking`; deleted write-only globals
  (window.CRM_SETTINGS, window.CRM_SETTINGS_CHAIN, S.stagedCache), dead state
  (S.emaills, S.extractionRunId, S.fileQueue, S.dedupChecking, S.page/pageSize
  mirrors), `void list` fetch (settings prompts load = 2 parallel fetches),
  dead `quality-detail-card` var, all unused imports flagged by an AST scan.
- Bulk approve now goes through the server bulk-action endpoint (one
  transaction) instead of N sequential client calls; bulk delete parallelized
  via allSettled; staged bulk loops deleted.
- `S.page/S.pageSize` manual mirrors deleted — loadContacts/search/filter use
  S.contactsPage directly; `stagedCursor` guards share `rowIdx()`;
  `loadStagedContacts()` call sites pass explicit page; the `null`
  mode-flag at renderStagedContactsTable became an explicit
  `rebindPagination` boolean; `debounce` used for search + palette search.
- Inline onclick contract retained; contract_audit MISSING DEFINITIONS: none,
  MISSING IDS identical to baseline; index.html wiring untouched except the
  boot script include.
- E2E (scratch HOME, Playwright): extract 3 files via real UI → staged 11 →
  keyboard triage → approve → contacts; bulk-approve button; theme toggle +
  density persistence across reload; hash navigation; palette; all views;
  **zero console/page errors**.
- Note: early E2E "failures" were test artifacts (server started from the
  wrong cwd serving the user's uncommitted WIP app.js) — resolved by
  restarting from this worktree; no defect was in the refactored code.
- Suite: **404 passed, 1 xfailed** (frontend changes don't touch tests).

## D-U6 (Phase 6 re-audit, done): first re-audit round — fixes

Subagent re-audit (backend) findings, fixed here; second round expected.

- **Approval seam keys (D-U1 enforcement)**: `_enrich_existing` now
  recomputes name_key/phone_key/company_key/website_key for every canonical
  field it fills (previously NULL keys forever); staged PATCH
  (`_apply_field_edits`) recomputes the staged row's keys for key-bearing
  fields it writes.
- **Merge is no longer a second approval path**: `/staged-contacts/{id}/merge`
  shares `_find_contact_by_identity` (email lower+phone_key fallback, same
  as approve) — previously email-only match, diverging from approve.
- **AI assist for documents**: adapters stash the parsed table on
  ExtractionResult (like .eml stashes `parsed`); the core no longer re-reads
  and re-parses xlsx/xls/pdf (and .txt gets AI assist for the first 500
  lines instead of silently getting none). The duplicate `contract_to_normalized`
  converter was deleted — one conversion boundary (`ai_contacts_to_staged`,
  pinned by chunking tests) + a direct kwarg spread into NormalizedContact.
- **Read-path ledger mutation removed**: `_pending()` no longer writes
  `processed_files` (status polls hit it). Oversized files are rejected by
  the extraction core (error ledger row) and drop out of pending after the
  scan — one cap, one place. test_security's size-cap test updated to the
  new contract (still asserts the ledger error row).
- **EML sort**: `_pending()` filters by is_processed BEFORE parsing Date
  headers — processed emails are never re-parsed just to sort them.
- **Migration consistency**: `_migrate_eml_data` recomputes email_key/
  phone_key instead of copying legacy verbatim; v4 backfill recomputes
  phone_key instead of legacy-first precedence.
- **Dead masking in app.py**: MASKED_KEY/_mask_chain/_mask_cfg/_merge_chain
  (all duplicated in api/settings.py, no callers) and unused ScanIn deleted;
  test_security imports MASKED_KEY from api.settings now.
- **Email regex unified**: keys.EMAIL_RE is the one regex; parse.py,
  eml_processor.py, parser.py, txt.py share it (parser's ASCII variant kept —
  deliberately different).
- **keys.py**: normalize_phone → private `_digits_only` (only is_duplicate
  uses it); dedup.py no longer re-exports keys (test-driven re-export
  removed); test_dedup imports keys directly.
- **AGENTS.md/CONTEXT.md** module references updated (eml_dedup_rules → keys.py).
- Suite: **401 passed, 1 xfailed**. contract_audit: identical (MISSING IDS
  subset is the no-charts rule, unchanged).

## D-U7 (Phase 6 re-audit, round 2): second round — fixes

Subagent re-audit #2 confirmed round-1 fixes hold. Fixed here:
- **api/intake.py paths channel deleted** — the `?paths=` form field was a
  documented dead security hole (INTERFACE_CONTRACTS §2.1: path-list form
  deleted, SEC-05/D-009): no UI/tests/tools call it; multipart bytes-only is
  the product contract. Its containment machinery went with it. Tests that
  pinned the deleted transport were converted to multipart (CSV-adapter and
  empty-file cases) or to a service-level nonexistence test; the "placeholder"
  test (asserted silent empty success on a missing file) deleted — its
  premise is impossible by design now. `test_api_intake_refuses_paths_outside_data_dirs`
  passes unchanged (400).
- **services/prompts/build_doc_request.py deleted** — fully unreferenced,
  pre-refactor dead code duplicating the live chunking path.
- **Chunking row anchoring**: `_row_line` now cites the adapters' absolute
  file `_row` (multi-sheet/pdf/csv correct), falling back to enumeration;
  AI-cited rows are traceable to the file again.
- **`_enrich_existing` self-heal**: after enrichment the canonical row's
  name/phone/company/website keys are ALWAYS recomputed from the final row
  (previously populated-but-keyless legacy rows could stay keyless).
- `services/parse.py` read_table docstring marks it evaluation-tooling API;
  adapters own production dispatch.
- Owner decisions deferred by design (see final report): adapter soft-fail
  contract (OK+warning vs hard ERROR for corrupt files — kept current),
  api/jobs.py stub, companies.website_key write-only column, raw_source_data
  D-017 accepted debt, .txt AI-assist cap.
- Suite: **400 passed, 1 xfailed**.

## D-U8 (Phase 6 re-audit, round 2 frontend): subagent findings, fixed

- **API wait-queue slot double-increment** (real bug introduced by the
  consolidation): a woken waiter was counted by both `_releaseSlot` and
  itself, leaking phantom slots. Fixed: waiter no longer self-counts.
- **Data Quality error path wrote to the Settings banner** — now writes the
  error into the quality view itself (`#quality-detail-list`).
- **`hashchange` accepted any view id** — now validated against VIEW_TITLES
  like the boot path.
- **`toggleDensity` fell through to the global toggle when a named table was
  missing** — now a no-op for unknown tableIds.
- Dead code removed: `S.companies`, `palette.built`, `opts.silent` on
  stagedDecide (uncalled), the four unpopulated `quality-*-list` divs
  (no server data source exists), `contactsContainer` id; two `data-title`
  strings synced to VIEW_TITLES; `paletteSearchContacts` is a function
  declaration; `setKpi` dead ternary removed; `aria-valuenow` synced during
  extraction; `density`/`theme`/`layout` audits re-confirmed clean.
- Pre-paint sidebar mismatch: not a bug — style.css keys off
  `html.sb-collapsed` which boot.js sets correctly.
- Suite: **400 passed**; contract_audit MISSING DEFINITIONS: none; browser
  E2E green again on final code (including bulk-approve UI call).
