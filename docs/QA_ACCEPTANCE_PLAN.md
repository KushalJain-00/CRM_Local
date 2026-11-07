# QA Acceptance Plan — CRM_Local

**Author:** qa-engineer (Round 2, brief §14.1)
**Date:** 2026-11-07
**Target HEAD:** `7610095` — "unified database, security fixes, extraction adapters, universal intake, settings, 9-view frontend, CI"
**Sources:** `docs/ACCEPTANCE_SCENARIOS.md` (D-024, authoritative A–G), `docs/CRM_FEATURE_PARITY.md`, `docs/STAGED_CONTACT_ARCHITECTURE.md` §5, `docs/ADVANCED_EXTRACTION_SPEC.md` §7, `docs/EXTRACTION_FIELD_MATRIX.md`, `DECISIONS.md` D-006..D-027.
**Scope note:** this plan is read-only investigation + this one file. No code, tests, or fixtures were changed or created. Fixture *creation* is specified here as plan items only (per D-025 and the round-2 brief).

---

## 1. Baseline — current test suite

### 1.1 Commands run (exact)

```sh
# venv exists but has no pytest:
cd /home/kushal_jain/PROJECTS/CRM_Local && ./venv/bin/python -m pytest -q
# → /home/kushal_jain/PROJECTS/CRM_Local/venv/bin/python: No module named pytest

# working invocation (system interpreter):
cd /home/kushal_jain/PROJECTS/CRM_Local && python3 -m pytest -q
```

### 1.2 Results

| Metric | Value |
|---|---|
| Collected | 58 |
| Passed | **58** |
| Failed | 0 |
| Skipped | 0 |
| Xfailed/xpassed | 0 |
| Duration | **181.71 s (3 m 01 s)** — ≈3.1 s/test |
| Warnings | 42 (deprecations only: `asyncio.iscoroutinefunction`, `datetime.utcnow`, PyMuPDF `fitz`) |
| Exit code | 0 |

**Test count audit:** prior audit claimed 58 — **verified**: `grep -c "def test_" tests/*.py` sums to 58 (adapters 14, app 7, db 4, dedup_rules 4, export 2, intake 3, llm 5, llm_validation 8, parse 6, pipeline 5).

### 1.3 Environment

| Item | Value |
|---|---|
| Interpreter used | `/usr/bin/python3` — **Python 3.14.7** |
| pytest | 9.1.1 (user site `~/.local/lib/python3.14/site-packages`) |
| App deps in run | fastapi 0.111.0, httpx 0.27.0, openpyxl 3.1.2, PyMuPDF 1.28.2 (user site) |
| `venv/` | Python 3.14.7, has app deps but **no pytest** (`requirements-dev.txt` never installed into it) |
| CI matrix (`.github/workflows/ci.yml`) | Python **3.11 / 3.12**, `python -m pytest tests/ -q` |
| **Skew** | Baseline proven only on 3.14.7 locally; CI proves 3.11/3.12 — see §6 |
| Tree state | HEAD `7610095`; **0 modified tracked files**; 9 untracked planning docs (`DECISIONS.md`, `PRODUCT.md`, `TASK_LOG.md`, `TEAM_BOARD.md`, 5× `docs/*.md`) |

### 1.4 What the suite does NOT cover (honest)

1. **No endpoint wiring tests** for `POST /api/intake`, `/api/jobs/*` (stubs), `/api/autostart`, `/api/test-llm`, `/api/open-folder`. `test_intake.py` exercises the *function*, not the HTTP route.
2. **The latent `intake.py:78` NameError** (`llm.extract` unbound when a non-empty chain reaches EML intake) has no test — the suite passes because `app.py:144` always passes `chain=[]`.
3. **Security:** zero tests for the confirmed secrets leak (`GET /api/config` returns `chain[].api_key`, `app.py:106-112`), zero prompt-injection tests, no formula-injection-on-CSV test (no CSV export exists), no log-redaction test. *A green suite today does not mean known security bugs are caught.*
4. **No PDF content tests** — `parse_pdf` (`services/parser.py`) is never called from any test; only `test_dispatch_pdf` checks the extension→adapter mapping.
5. **No migration tests** — nothing verifies `STAGED_CONTACT_ARCHITECTURE.md` §5 v2–v9, the D-016 backup/count-verification discipline, or live-baseline preservation (55/60/47).
6. **No staging/approval/merge tests** — the features don't exist yet (Phase 1–2), so Scenarios A7–A10, B7–B8, C7, C9–C10, D6–D7, E3–E7, F6, G6–G7 have zero coverage by construction.
7. **No UI/e2e, no a11y, no performance tests**; no `tests/fixtures/` directory at all (all data is built inline in `tmp_path`).
8. **No coverage gate** in CI (brief target ≥80% per prior audit); no policy checks (charts/CDN/sleep greps).
9. **Dedup known bug unguarded:** name-only auto-merge (`db.py:384-387`) violates "same name ≠ same person" — no failing test forces the fix.
10. **Slow-for-its-size:** 3 m 01 s for 58 mostly-unit tests; there is headroom to find the slow tests (likely LLM chain tests) before adding hundreds more.

---

## 2. Scenario A–G traceability matrix

Verbatim steps from `docs/ACCEPTANCE_SCENARIOS.md` (D-024). Every one of the **57 steps** appears.
Legend — Existing: ✅ real coverage · ⚠ partial/tangential · ❌ none. Blocked-by: the phase whose deliverable the step needs; "—" means the planned test can be written **now**.

**Totals: 24/57 steps have some existing test (mostly partial); 33/57 have none.**

### Scenario A — Spreadsheet (10 steps): 6 partial · 4 none

| # | Step (verbatim) | Existing test | Planned test (level) | Blocked-by |
|---|---|---|---|---|
| A1 | Import a spreadsheet with multiple sheets | ⚠ `test_parse.py::test_xlsx_parses_numeric_cells` (single sheet) | `test_a1_multi_sheet_import` (integration) | — |
| A2 | Detect fields | ⚠ `test_parse.py::test_csv_parses_and_maps_columns`, `test_xlsx_parses_numeric_cells` (alias map only) | `test_a2_detects_mapping_types` (unit) — 25-type detection, D-023 | Phase 1 (server-side detection) |
| A3 | Map columns | ⚠ `test_parse.py::test_secondary_columns_win_over_primary_aliases` | `test_a3_mapping_session_persisted` (integration); UI confirm = e2e | Phase 4 (mapping UI, D-023) |
| A4 | Extract company information | ❌ | `test_a4_company_extraction_with_evidence` (integration) | Phase 1 (companies writer — `companies` has zero writers today) |
| A5 | Extract contacts | ⚠ `test_intake.py::test_universal_intake_csv` | `test_a5_contacts_staged_not_canonical` (integration) | Phase 2 (staging, D-006/D-007) |
| A6 | Preserve unmapped values | ❌ (parse discards 14+ mapping types today) | `test_a6_unmapped_values_in_raw_source` (integration) | Phase 1 (`raw_source_data`, D-017) |
| A7 | Stage contacts | ❌ | `test_a7_intake_writes_staged_only` (integration) | Phase 2 (`staged_contacts` does not exist) |
| A8 | Detect duplicates | ⚠ `test_db.py::test_dedup_index_matches_email_phone_and_name`, `test_dedup_rules.py::test_is_duplicate_email` | `test_a8_dedup_tier_classification` (unit) | Phase 1–2 (3-dimension dedup status) |
| A9 | Approve selected records | ❌ | `test_a9_bulk_approve_selected` (integration); click path = e2e | Phase 2 (approval endpoint) |
| A10 | Verify final CRM data | ⚠ `test_db.py::test_upsert_enriches_without_overwriting` | `test_a10_approved_rows_in_canonical_with_provenance` (integration) | Phase 2 |

### Scenario B — PDF (8 steps): 1 partial · 7 none

| # | Step (verbatim) | Existing test | Planned test (level) | Blocked-by |
|---|---|---|---|---|
| B1 | Import multiple PDFs | ⚠ `test_adapters.py::test_dispatch_pdf` (**extension dispatch only — no content test exists**) | `test_b1_multi_pdf_import` (integration) | Phase 4 (dropzone transport, D-009); fixture can be built now |
| B2 | Extract text and tables | ❌ `parse_pdf` never called by any test | `test_b2_pdf_text_and_tables` (unit — `services/parser.py`) | — (write now) |
| B3 | Identify company information | ❌ | `test_b3_pdf_company_identification` (integration) | Phase 1 |
| B4 | Identify multiple people | ❌ | `test_b4_pdf_multiple_people` (integration) | Phase 1 |
| B5 | Preserve page references | ❌ (no per-field evidence exists anywhere) | `test_b5_page_evidence_location` (integration) | Phase 1 (evidence `location` = `page N`) |
| B6 | Validate results | ❌ | `tests/test_validation.py::test_b6_pdf_flagged_values` (unit) — spec §7.1 exact strings | Phase 1 (validation engine) |
| B7 | Stage contacts | ❌ | `test_b7_pdf_staged` (integration) | Phase 2 |
| B8 | Approve or correct candidates | ❌ | `test_b8_approve_or_correct_staged` (integration); correction UI = e2e | Phase 2 (approve); Phase 6 (correct UI) |

### Scenario C — EML (10 steps): 4 partial · 6 none

| # | Step (verbatim) | Existing test | Planned test (level) | Blocked-by |
|---|---|---|---|---|
| C1 | Import multiple email messages | ⚠ `test_adapters.py::test_eml_adapter_basic`, `test_pipeline.py::test_scan_processes_eml_and_pushes_to_crm` (single EML) | `test_c1_multi_eml_import` (integration) | Phase 2 |
| C2 | Preserve original email content | ❌ intake path writes **no `eml_emails` row at all**; pipeline skips contact-less mails before `insert_email` | `test_c2_email_preserved_even_without_contact` (integration) | Phase 5 (P-10) / Phase 2 |
| C3 | Extract deterministic headers | ❌ (logic in `services/eml_processor.py` exercised only indirectly) | `test_c3_deterministic_headers` (unit) | — (write now) |
| C4 | Extract sender signatures | ❌ | `test_c4_signature_block_extraction` (unit) | — (write now) |
| C5 | Identify genuine contact candidates | ⚠ `test_parse.py::test_row_without_email_or_phone_is_dropped` (spreadsheet path only) | `test_c5_no_false_contact_signature_only` (integration, spec §7.3) | Phase 1 |
| C6 | Preserve To/CC/BCC | ❌ | `test_c6_to_cc_bcc_preserved` (integration) | Phase 1 (D-022 `receiver_*` columns) |
| C7 | Stage contacts | ❌ | `test_c7_eml_staged_unified` (integration) | Phase 2 |
| C8 | Resolve duplicate candidates | ⚠ `test_dedup_rules.py::test_is_duplicate_email`, `test_normalize_email` | `test_c8_duplicate_resolution_flow` (integration); workspace UI = e2e | Phase 2–3 |
| C9 | Approve and enrich | ⚠ `test_db.py::test_upsert_enriches_without_overwriting`, `test_pipeline.py::test_llm_fields_do_not_override_local` | `test_c9_approve_then_enrich_local_wins` (integration) | Phase 2 |
| C10 | Verify email relationships | ❌ | `test_c10_email_contact_relationships` (integration — `email_staged_links`/`contact_emails`) | Phase 2 (tables v3); Phase 5 (browser UI) |

### Scenario D — Enrichment (7 steps): 5 partial · 2 none

| # | Step (verbatim) | Existing test | Planned test (level) | Blocked-by |
|---|---|---|---|---|
| D1 | Import a contact already in CRM | ⚠ `test_db.py::test_upsert_enriches_without_overwriting` | `test_d1_reimport_existing_contact` (integration, via staging) | Phase 2 |
| D2 | Provide additional phone or company information | ⚠ same | `test_d2_additional_phone_company` (integration) | Phase 1 (company side) |
| D3 | Detect the existing contact | ⚠ same (email/phone match inside `upsert_contact`/`_find`) | `test_d3_detect_existing_by_email_phone` (unit) | — (strengthen now) |
| D4 | Fill missing fields | ⚠ same | folded into `test_d2`/`test_d5` | — |
| D5 | Preserve existing populated values | ⚠ same + `test_pipeline.py::test_llm_fields_do_not_override_local` | `test_d5_never_overwrite_populated` (unit, made strict) | — (strengthen now) |
| D6 | Record provenance | ❌ provenance columns exist but **0 rows populated** (`intake.py:94-105` drops them) | `test_d6_provenance_on_enrichment` (integration) | Phase 1 (D-016) |
| D7 | Verify the source relationship | ❌ | `test_d7_staged_source_link_after_enrich` (integration) | Phase 1–2 |

### Scenario E — Duplicate review (7 steps): 1 partial · 6 none

| # | Step (verbatim) | Existing test | Planned test (level) | Blocked-by |
|---|---|---|---|---|
| E1 | Create exact duplicate candidates | ⚠ `test_db.py::test_dedup_index_matches_email_phone_and_name` | `test_e1_exact_duplicate_candidates` (integration, over staging) | Phase 2 |
| E2 | Create probable duplicates | ❌ name+company tier untested | `test_e2_probable_duplicate_tiers` (unit) | — (write now — P0) |
| E3 | Identify conflicts | ❌ `field_conflicts` table doesn't exist (v3) | `test_e3_conflict_identification` (integration) | Phase 1 (v3 tables) |
| E4 | Compare field values | ❌ | `test_e4_field_comparison_payload` (integration); UI = e2e | Phase 3 (duplicates workspace) |
| E5 | Merge selected fields | ❌ | `test_e5_field_level_merge` (integration) | Phase 3 |
| E6 | Preserve email and activity relationships | ❌ | `test_e6_merge_preserves_relationships` (integration) | Phase 3 |
| E7 | Verify recovery behaviour | ❌ (D-014 merge audit/undo not built) | `test_e7_merge_undo_from_audit` (integration) | Phase 3 (D-014) |

### Scenario F — Offline usage (7 steps): 5 partial · 2 none

| # | Step (verbatim) | Existing test | Planned test (level) | Blocked-by |
|---|---|---|---|---|
| F1 | Disable internet | ❌ | `test_f1_local_only_blocks_network` (integration: socket-level connect guard + `mode=local_only` + provider chain empty → all six fixtures still extract); optional CI smoke under `unshare -rn` — **method in §3.18 tie-in and §4.4**; physical "disable NIC" check stays manual | Phase 4 (user-facing local-only toggle) |
| F2 | Launch CRM_Local | ⚠ `test_app.py::test_index` (TestClient — not a real launch) | packaged launch = `scripts/verify_windows_launch.ps1` (§6) | **🌍 BLOCKED-ENV (Windows)** — cannot launch/verify the PyInstaller exe here |
| F3 | Import supported local files | ⚠ `test_intake.py::test_universal_intake_csv/empty/unsupported` | `test_f3_all_six_formats_import` (integration, one fixture per format) | — (fixtures per §4.3; full flow Phase 2) |
| F4 | Perform local extraction | ⚠ `test_pipeline.py::test_llm_fields_do_not_override_local`, `test_llm.py::test_empty_chain_reports_local_only` | `test_f4_deterministic_extraction_offline` (integration) | Phase 1 (spec §7.3 offline check) |
| F5 | Manage contacts | ⚠ `test_app.py::test_contacts_list`, `test_contacts_invalid_which` | `test_f5_contacts_crud` (integration); real UI = e2e | Phase 3 (sort/filter/bulk); e2e Phase 6 |
| F6 | Review staged records | ❌ | `test_f6_staged_review_offline` (integration) | Phase 2 |
| F7 | Export results | ⚠ `test_export.py::test_export_writes_styled_sheet_with_headers`, `test_export_handles_empty_rows` | `test_f7_export_formats_offline` (integration, all 5 formats) | Phase 3 (CSV/PDF/VCF/ZIP per D-013) |

### Scenario G — Restart and recovery (8 steps): 2 partial · 6 none

| # | Step (verbatim) | Existing test | Planned test (level) | Blocked-by |
|---|---|---|---|---|
| G1 | Process a batch | ⚠ `test_pipeline.py::test_scan_processes_eml_and_pushes_to_crm` | `test_g1_batch_processed` (integration) | Phase 2 |
| G2 | Close the application | ❌ | `test_g2_shutdown_persists` (integration: process batch → dispose app/DB → reopen same file); *real* windowed-exe close = manual on Windows | Phase 8 (exe); in-process version now |
| G3 | Restart | ❌ | same test as G2 (in-process restart); cross-process = Windows script §6 | — |
| G4 | Verify database integrity | ❌ | `test_g4_integrity_after_restart` (integration: `PRAGMA integrity_check` + `foreign_key_check`) + **migration verification suite (P0-1)** | Phase 1 (migration train) |
| G5 | Verify contact records | ❌ | `test_g5_counts_survive_restart` (integration) | — (write now) |
| G6 | Verify staged records | ❌ | `test_g6_staged_survive_restart` (integration) | Phase 2 |
| G7 | Verify email relationships | ❌ | `test_g7_email_links_survive_restart` (integration) | Phase 2 (v3/v5) |
| G8 | Verify settings and history | ⚠ `test_app.py::test_settings_get`, `test_config_get` (read-only, no restart) | `test_g8_settings_and_history_survive_restart` (integration) | Phase 1 (single settings surface, D-011) |

> **Stale-doc warning:** `docs/ADVANCED_EXTRACTION_SPEC.md` §7.4 maps "scenarios A–G" to its own provisional readings (dropzone folder, offline, enrichment…). Those letters **do not match** the now-authoritative `docs/ACCEPTANCE_SCENARIOS.md` (D-024). This plan supersedes §7.4; §7.4 should be marked stale by its author.

---

## 3. Gap analysis & priorities

### P0 — blocks Phase 1–2 acceptance (build in the same PRs as the features)

| ID | Gap | Proposed tests (level) | Ties to |
|---|---|---|---|
| **P0-1** | **Migration verification** — nothing tests STAGED §5 v2–v9; a botched v6 `contacts` rebuild destroys the canonical table | `tests/test_migration.py`: `test_step0_backup_created_before_migration`, `test_v2_v9_apply_in_order`, `test_v6_rebuild_preserves_row_count_and_columns` (baseline 55), `test_v7_view_returns_47`, `test_migration_idempotent_rerun`, `test_integrity_and_fk_check_clean`, `test_rollback_restores_backup` (integration, tmp DB + synthetic legacy `eml.db`) | D-016, DoD "no data loss", Scenario G4 |
| **P0-2** | **Staging round-trip** — intake→canonical has no approval gate test | `tests/test_staging.py`: `test_intake_writes_staged_not_canonical`, `test_approve_writes_canonical_exactly_once`, `test_reject_leaves_canonical_untouched`, `test_approve_sets_provenance`, `test_duplicate_approve_is_idempotent` (integration) | D-006/D-007, A7/A9/A10, C7/C9 |
| **P0-3** | **Canonical-write-path single-ness** — `pipeline.py` + `intake.py` are two orchestrators with divergent mapping/dedup | `tests/test_orchestrator_parity.py::test_intake_and_scan_produce_identical_staged_rows` (integration, same input file both paths — explicitly proposed by spec §7.1) + **static gate**: grep test asserting `intake.py`/`pipeline.py` contain no direct `upsert_contact`/`insert_eml_contact` calls after Phase 2 | Brief §13 one-of-everything; A5/C1 |
| **P0-4** | **Contract validation** — the extraction JSON contract has no checker tests | `tests/test_contract.py`: reject missing `schema_version`, extra key (`id`, `created_at`), wrong `source_type`, array type errors, missing `field_evidence` on a populated field, non-empty `call_logs` on ungated source, MIME-vs-AI metadata conflict (unit) | spec §7.1, DoD evidence requirements |
| **P0-5** | **Local-wins enrichment** — only happy path covered; conflict case not strict | `tests/test_enrichment.py::test_local_wins_ai_alternative_stored` (integration, fixture where Layer-1 and Layer-2 disagree) + tighten `test_d5_never_overwrite_populated` to strict | D-026, C9, D5, spec §7.3 |
| **P0-6** | **Dedup no-false-merge** — name-only auto-merge bug (`db.py:384-387`) has no failing test | `tests/test_dedup_rules.py`: `test_name_only_never_auto_merges`, `test_same_name_different_company_no_merge`, `test_conflict_same_email_different_name_flags_not_merges` (unit) + integration tier test | Scenario E1–E3, DoD "review before commit" |
| **P0-7** | **Known-bug characterization tests (strict xfail)** — green suite currently hides 3 confirmed bugs | `@pytest.mark.xfail(reason="D-011: secrets leak app.py:106-112", strict=True) test_config_get_masks_api_key`; `xfail(strict=True)` for `intake.py:78` NameError with non-empty chain; `xfail(strict=True)` for dropzone transport (`app.js:114` bare filenames). **strict=True**: when the fix lands, XPASS fails CI and the marker must be removed in the same PR — a ratchet, not a excuse | D-009, D-011; parity doc §1.3 |
| **P0-8** | **Security regression seeds (do not wait for `docs/SECURITY_REVIEW.md`)** | Start now with: secrets-masked GET (above), `test_prompt_injection_payload_is_treated_as_data` (port shape from reference `[Dev] tests/test_prompt_injection.py`), `test_export_formula_injection_sanitized` (XLSX today), `test_security_headers_present`, `test_openapi_disabled`, `test_loopback_bind`. **Interface with the concurrent security doc:** when `docs/SECURITY_REVIEW.md` lands, every control it lists gets a test ID appended to this matrix; QA does not block on the doc | DoD security items, brief "secrets NEVER exposed to browser JS" |

### P1 — required before Phase 5 exit

| ID | Gap | Proposed tests |
|---|---|---|
| P1-1 | **Per-format extraction fixtures for all 6 formats** (§4.3) — only txt/csv/eml have content tests; xlsx single-sheet; xls/pdf content = 0 | integration suite `tests/test_extraction_fixtures.py`, one test per format asserting staged row count, source metadata (sheet/page/row), evidence per populated field, validation issues for planted bad values, **no canonical write without approval** |
| P1-2 | **Review queue workflows** (tabs/filters over the 3 status dimensions) | `tests/test_review_queue.py`: filter by review/dedup/import status, paging, bulk approve/reject with partial-failure reporting (integration) |
| P1-3 | **Bulk operations** | `test_bulk_approve`, `test_bulk_reject`, `test_bulk_delete_transactional` (integration; all-or-nothing semantics asserted) |
| P1-4 | **Email relationships** (C10, G7) | `tests/test_email_links.py`: staged↔email↔contact linkage survives approve/merge/restart |
| P1-5 | **Validators — spec §7.1 exact strings** | `tests/test_validation.py`: `image001.png@01dd4100.ede`→SUSPICIOUS, `share the quotation asap.`→SUSPICIOUS-as-name, `Depth.- 900 FT. Borewell…`→SUSPICIOUS-as-company, IN/landline/INTL phone classify, pincode IN/non-IN, unfamiliar-domain email accepted |
| P1-6 | **Prompt assembly** | `tests/test_prompt_assembly.py`: master text verbatim, exactly one source extension, untrusted delimiters present, **no API key in messages** |
| P1-7 | **No-invention / no-false-contact accuracy** (spec §7.3) | golden sets: N fields must stay null; TXT prose → 0 contacts; EML with 3 names + 1 signature → only evidenced contact(s) |
| P1-8 | **Jobs endpoints** | tests forcing real job state or deletion of the `app.py:148-157` stubs (today they unconditionally return `done`/`cancelled`) |
| P1-9 | **Offline full matrix** (F1/F4) | all six fixtures extract under `local_only` + blocked sockets |
| P1-10 | **Call-log extraction** (D-025) | build synthetic structured-call CSV fixture (shape below, **fixture not yet written — QA owns it per D-025**), then `test_call_csv_extracts_only_when_structured`; gate stays "explicitly structured only" (field matrix §E); check reference repo for fixtures during Phase 3 |

**D-025 synthetic call-log fixture — exact spec (plan item, do not create yet):**
`tests/fixtures/calls_structured.csv`, headers exactly:
`contact_name,company_name,call_date,duration_minutes,call_type,outcome,notes,next_action,next_action_date`
— plus a negative twin `calls_unstructured.csv` (free-text notes with dates/phone numbers embedded, no such headers) that must yield **0** call rows. Rows must reference contacts that also exist in the duplicate corpus so relationship tests can resolve `contact_id`.

### P2 — required before Phase 8 exit

| ID | Gap | Proposed tests |
|---|---|---|
| P2-1 | **UI/e2e** (Playwright) — no browser test exists at all | Phase 6: e2e for the 5 money paths: drop→stage→approve, contacts search/sort/page, duplicates merge, settings mask, export. See §4.4 feasibility |
| P2-2 | **Exports beyond XLSX** | CSV/PDF/VCF/ZIP output tests + formula-injection sanitize on CSV (D-013) |
| P2-3 | **Command palette** | e2e: Ctrl/Cmd+K opens, navigates, closes; a11y focus trap |
| P2-4 | **Performance at 10k** | `tests/test_performance.py` (§4.5): response budget, page integrity, index-backed query plan |
| P2-5 | **Coverage gate** | add `pytest-cov`; ratchet: report-only first, enforce ≥80% on changed files once Phase 3 lands (prior audit's stated target) |
| P2-6 | **a11y** | axe-core run in e2e against WCAG 2.2 AA (skip link missing today, parity §1.2) |
| P2-7 | **Visual regression** | optional separate lane — see honest `.reticle/` assessment in §4.4 |

### DoD (brief §18) tie-ins — three specific checks

1. **"No charts anywhere" → static grep check.** Add to CI as a policy job:
   ```sh
   ! grep -rniE "chart\.js|addBarChart|addDonutChart|<canvas" static/ && \
   ! grep -rniE "chart-" static/index.html
   ```
   **Expected result today: FAIL** — `static/index.html:133-136` still has `chart-*` ids (Analytics view; D-012 deletes it). Record as known-red; the gate must be green by end of Phase 6. Do not weaken the grep when it goes in — land it with D-012.
2. **Offline Scenario F → method** (not just "turn off wifi"):
   - *Automatable:* integration test sets `mode=local_only` + empty chain, monkeypatches `socket.socket.connect`/`create_connection` to raise, stubs `llm.extract` to raise if ever called, then runs all six format fixtures end-to-end. Any network attempt fails the test.
   - *CI smoke (optional, best-effort):* run the same suite under `unshare -rn` on the Linux runner; if the runner denies network namespaces, mark the step `continue-on-error` and keep the socket-level test as the hard gate.
   - *Manual (Windows, §6):* launch packaged exe with NIC disabled, import one file of each format, export — scripted in `verify_windows_launch.ps1`.
3. **Security items → interface with `docs/SECURITY_REVIEW.md` (being written concurrently).** QA does not wait: P0-8 seeds run now. Contract: when the security doc lands, QA maps **every** listed control to a test ID in §2's matrix (new column or appendix), and any control without a test becomes a P0 gap. Expected test files: `tests/test_security_secrets.py`, `test_security_injection.py`, `test_security_headers.py` (names finalised when the doc's control list is known).

---

## 4. Test architecture proposal

### 4.1 Layer split for THIS repo

| Layer | Runner | What lives here | Rules |
|---|---|---|---|
| **Unit** | pytest (present) | pure functions: `parse.py`, `eml_dedup_rules.py`, `llm.py` validators, contract checker, validators, normalizers, dedup tiers | no network, no real DB (or `tmp_path` DB via existing `data_dir` fixture); target <50 ms/test |
| **Integration** | pytest + FastAPI `TestClient` + tmp SQLite (`tests/conftest.py::data_dir` already does this well) | endpoints, intake↔pipeline parity, staging round-trip, migrations, fixtures-per-format, restart/recovery, performance seeding | setup through the API/factory; assert through the API; one fixture per test owns its tmp dir (already the pattern — keep it) |
| **E2E** | **Playwright** (new, Phase 6) | hash-router journeys across views, command palette, a11y, visual | starts real `uvicorn` on loopback port; API seeds data, UI asserts; **no sleeps** — wait on network responses/DOM state |
| **Policy/static** | CI shell greps (no pytest needed) | no-charts, no-CDN, no `time.sleep`/`waitForTimeout` in tests/static, secrets not in `static/`, canonical-write-path single-ness (P0-3) | fastest possible feedback; runs first in CI |

Playwright e2e is **feasible**: vanilla-JS SPA, hash routing, loopback server, no auth wall. Cost: Node toolchain in CI + a port-picker helper (app binds 8000–8010, `app.py:301-311`). Decision: introduce in Phase 6, not before — UI churn before then makes e2e scripts rewrite bait.

### 4.2 Existing-infra reuse

- `tests/conftest.py::data_dir` (monkeypatches `config.data_dir` → tmp, calls `db.init()`) is the right isolation pattern — extend it, don't replace it.
- `requirements-dev.txt` already pins `pytest==9.1.1` — add `pytest-cov` (P2-5) and, later, `playwright` in a separate `requirements-e2e.txt` so backend CI stays lean.

### 4.3 Fixture strategy — one fixture per format (+ corpora)

Create `tests/fixtures/` with a committed generator script (`build_fixtures.py`, deterministic seeds) **and** the generated outputs, so binaries are reproducible:

| Fixture | Shape | Serves |
|---|---|---|
| `multi_sheet.xlsx` | 3 sheets: contacts sheet, company sheet, junk sheet | A1, A4, sheet provenance (B5 analog) |
| `contacts.xls` | BIFF via xlrd, float phones | xls adapter content (currently untested) |
| `contacts_variants.csv` | delimiters `,` `;` `\t` × encodings utf-8 / latin-1 / gbk, BOM | csv robustness, encoding matrix |
| `report.pdf` | 3 pages: prose p1, table p2, second person p3 | B1–B5 (page refs, multi-person, tables) |
| `phones.txt` | phone list **+ prose paragraph** | F3, no-false-contact (prose → 0 contacts) |
| `signature.eml` | multi-recipient To/CC/BCC, signature block, **prompt-injection payload in body** | C1–C6, P0-8 injection test |
| `calls_structured.csv` + `calls_unstructured.csv` | D-025 exact headers / free-text negative | P1-10 (fixture = plan item, D-025) |
| `duplicates/` corpus | exact pair, probable pair (name+company), conflict pair (same email diff name), same-name-different-person | E1–E3, P0-6, A8 |
| `golden/*.json` | expected extraction per fixture, with explicit `null` fields | P1-7 no-invention |

### 4.4 Offline / e2e / `.reticle/` assessment (honest)

- **Offline:** method in §3 DoD tie-in #2 — socket-level guard is the hard, portable gate; `unshare` is best-effort.
- **Browser e2e: not present.** No Playwright/Cypress anywhere; `requirements-dev.txt` has only pytest.
- **`.reticle/` prior visual-regression infra:** 5 saved drive flows (`.reticle/flows/*.json`), 9 baseline PNGs (`.reticle/visual/`), `project.json` with one learned route `/`. **Honest verdict: not reusable as a regression suite.** The flows drive pre-Phase-6 UI ("type path into run page", "scan now", "contacts tabs", "download excel") — every one encodes controls that the ES-module/13-view rebuild will remove; the PNGs are one-time snapshots of a UI slated for Phase 6 redesign; and the flows contain **no assertions** — they are drivers, not tests. Reuse: keep Reticle for interactive change-verification *during* development (its gate proves a journey end-to-end), but the durable automated layer is Playwright in Phase 6, and visual regression (if wanted) becomes a separate intentional lane with per-component thresholds — never bolted onto functional tests.

### 4.5 Performance factory — 10k contacts

- `tests/factories.py::seed_contacts(n=10_000)` — single-transaction `executemany` into tmp DB (~1–2 s; a per-row `upsert_contact` loop would take minutes — do not use it).
- Assertions:
  1. **Response time:** `GET /api/contacts?page=1&size=50` p95 < 300 ms over 20 iterations locally (500 ms on CI runners), measured with `time.perf_counter` — no sleeps, just repeated calls.
  2. **Page integrity:** pages 1..200 are pairwise disjoint, union size = 10 000, ordering stable across calls (no duplicate/skip under `ORDER BY id DESC`).
  3. **No full-table load:** `EXPLAIN QUERY PLAN` for the list query must not show a full `SCAN contacts` when `q` is empty (today `db.py:484-493` does `LIKE '%q%'` + no sort params — this test will document current behavior first, then tighten); response body row count == `size` exactly.
  4. Search path (`?q=`) gets its own budget once Phase 5 decides FTS5 vs LIKE (D-020).

### 4.6 CI wiring (`.github/workflows/`)

Current: `ci.yml` (ubuntu, py 3.11+3.12, `python -m pytest tests/ -q`) and `windows-build.yml` (windows, pytest → PyInstaller → exe existence check → Inno, last two `continue-on-error: true`).

Proposed changes (for the devops engineer; QA specifies, does not edit):

1. **Keep `python -m pytest tests/ -q` as the one backend test command** — it survives the D-010 `api/` router split as long as `tests/conftest.py`'s `sys.path` insertion and any `from app import …` imports are updated in the same PR (D-010 makes that the backend engineer's checklist item; QA adds a CI import-smoke test).
2. **Add a `policy` job** (shell, seconds): no-charts grep, no-CDN grep (`<script src="http` / `<link … href="http` in `static/`), no `time.sleep`/`waitForTimeout` in `tests/` and `static/`, secrets-not-in-static.
3. **Add Python 3.14 to the matrix** (or pin dev to 3.12) — today the only *proven* local env (3.14.7) differs from CI (3.11/3.12); that skew is untested ground.
4. **Coverage:** report first, gate later (P2-5).
5. **E2E workflow (Phase 6):** separate `e2e.yml` — `pip install -r requirements-e2e.txt && npx playwright install --with-deps chromium`, boot `uvicorn app:app`, run `npx playwright test`; artifacts (trace/screenshot/video) uploaded on failure.
6. **Windows workflow:** add the smoke-run step from §6.

---

## 5. Regression policy — shared byte-identical services

`services/eml_processor.py`, `services/eml_dedup_rules.py`, `services/parser.py` are **byte-identical to CRM_Developer** (verified by `diff` in the parity audit). Both repos must stay in sync (one-of-everything).

**Proposed parity check — `tests/test_shared_parity.py`:**

```python
REF = Path(os.environ.get("CRM_DEV_REPO", "/home/kushal_jain/PROJECTS/CRM_Developer"))
SHARED = ["services/eml_processor.py", "services/eml_dedup_rules.py", "services/parser.py"]

@pytest.mark.skipif(not (REF / "services").exists(),
                    reason="reference repo not present (CI) — behavior tests below still apply")
@pytest.mark.parametrize("rel", SHARED)
def test_shared_service_byte_identical(rel):
    assert sha256(Path(rel).read_bytes()) == sha256((REF / rel).read_bytes()), (
        f"{rel} diverged from CRM_Developer — mirror the change or record a DECISIONS entry"
    )
```

Rules around it:

1. **The hash test runs only where the reference repo exists** (local dev). CI does not have CRM_Developer → it skips. Therefore it is necessary but **not sufficient**.
2. **Sufficient-in-CI: mirrored behavior tests.** Every shared function's contract is pinned by *behavior* tests in this repo (`test_dedup_rules.py`, `test_pipeline.py::test_llm_fields_do_not_override_local`, EML fixtures). Policy: any change to a shared file must keep these green **and** update the reference copy in the same change; if divergence is intentional, a `DECISIONS.md` entry is mandatory (the hash test's failure message says exactly that).
3. When new shared logic appears (e.g. contract checker), it lands in `services/` with tests in `tests/` from day one — no test lives only in the reference repo.

---

## 6. Environment limits — honest section

### 6.1 BLOCKED-ENV: Windows packaging cannot be verified on this Linux machine

Not verifiable here: PyInstaller exe build **and run**, Inno Setup silent install/uninstall, Start Menu/autostart (`app.py:259-283`, Windows-only + frozen-only), native tkinter folder picker, `%APPDATA%` data-dir resolution (`config.py:8-18`), windowed-exe guard (`app.py:9-11`), browser auto-open when frozen.

**Existing partial coverage:** `windows-build.yml` already runs pytest, builds `CRM_Local.exe`, and checks *existence + size*. It never **runs** the exe and the installer steps are `continue-on-error: true` (they can silently rot).

**Required verification (must run on Windows — CI job or manual pre-release):**

```powershell
# scripts/verify_windows_launch.ps1 — QA specifies; devops implements in Phase 8
# 1. Launch headless-smoke: start dist\CRM_Local.exe with CRM_LOCAL_SMOKE=1
#    (requires a smoke flag in main() — feature request, Phase 8)
# 2. Poll http://127.0.0.1:<port>/api/status until HTTP 200 (max 20 s)
# 3. Assert response JSON has counts + providers; assert data_dir = %APPDATA%\CRM_Local\crm.db created
# 4. Stop process; relaunch; assert /api/status again (restart = Scenario G2/G3 packaged)
# 5. ISCC.exe CRM_Local.iss; Start-Process dist\CRM_Local-Setup.exe /S; assert install dir + shortcut
# 6. Uninstall silently; assert removal (leaving %APPDATA% data intact — data must survive uninstall)
```

Scenario steps marked **BLOCKED-ENV** until that runs: **F2** (launch), **G2/G3** packaged variants, plus packaging DoD items. The Linux-side equivalents (in-process restart tests G2–G8) are *not* blocked and are planned above.

### 6.2 Browser e2e not yet present

No Playwright/Cypress dependency, no e2e workflow, no `.reticle/` assertion suite (§4.4). Until Phase 6, every UI-only step in §2 (mapping UI confirm, correction UI, duplicate-compare UI, command palette) is **manual-only** — flagged as such in the matrix.

### 6.3 Other honest limits

- Baseline proven on Python 3.14.7 only; CI proves 3.11/3.12; nobody has run the suite on 3.14 in CI (§4.6.3).
- The venv in-repo cannot run tests as-is (`pytest` not installed into it) — anyone following README/venv instructions hits `No module named pytest`.
- The 42 deprecation warnings (`datetime.utcnow`, `iscoroutinefunction`) are future-Python breakage risk, not failures — worth a P2 cleanup ticket, not a gate.
- Live-DB migration baselines (55/60/47) come from STAGED doc's 2026-11-07 snapshot; migration tests must therefore build **synthetic** baselines, never depend on a developer's real `crm.db`.

---

## 7. Acceptance gate definition ("Phase N done", test-wise)

The orchestrator's review loops enforce this checklist at every phase review:

1. **Green suite:** `python3 -m pytest -q` (and CI `python -m pytest tests/ -q` on 3.11/3.12) exits 0 on the phase's merge commit. Zero failures, zero skips without a recorded reason.
2. **Scenario coverage advanced:** every §2 row *assigned to Phase N* has (a) a passing planned test, or (b) an explicitly documented manual check with instructions — no row silently left behind. Rows blocked by later phases stay marked blocked; they don't block Phase N.
3. **Feature = test:** no functionality merges without its tests in the same change (backend: pytest; UI: at minimum an integration/API-level test until Phase 6 adds e2e). A feature PR whose tests are "added later" is not done.
4. **No silent xfails:** new `xfail` requires a `DECISIONS.md` entry; existing strict-xfails (P0-7) **must flip** — marker removed — the moment their decision (D-009/D-011) lands. Strict-XPASS failing CI is the intended ratchet.
5. **Policy greps green** (no-charts after D-012, no-CDN, no-sleeps) — introduced per §3 DoD tie-in #1.
6. **Phase-specific exits:** Phase 2 cannot close until all **P0** rows are green (migration verification, staging round-trip, write-path single-ness, contract validation, local-wins, no-false-merge). Phase 5 closes on all **P1** rows. Phase 8 closes on all **P2** rows + the Windows BLOCKED-ENV script run.
7. **Budgets:** full backend suite < 10 minutes; any new test > 5 s gets justified or split; e2e failures must be debuggable from attached trace/screenshot alone.
8. **Flake discipline:** a test that fails once and passes on rerun is quarantined within 24 h with a root-cause ticket — never deleted, never retried into green.

---

## Report

- **Doc:** `docs/QA_ACCEPTANCE_PLAN.md` (this file — the only file written; no code/tests/fixtures touched, nothing committed).
- **Baseline:** `python3 -m pytest -q` → **58 collected / 58 passed / 0 failed / 0 skipped, 181.71 s, 42 deprecation warnings, exit 0** — on Python 3.14.7 + pytest 9.1.1 (system); `venv/` lacks pytest; CI runs 3.11/3.12. Prior audit's count of 58 verified.
- **Scenario coverage:** 57 total steps — **24 with existing test coverage (all partial/tangential), 33 with none**; additionally 1 step hard BLOCKED-ENV (F2) and ~4 UI-only steps manual-until-Phase-6.
- **Top 3 test gaps by risk:**
  1. **No migration verification (P0-1)** — the D-016 `contacts` rebuild can destroy the canonical table; zero tests guard the 55/60/47 baselines, backup, or rollback. Highest data-loss risk in the project.
  2. **No canonical-write-path single-ness / staging round-trip tests (P0-2, P0-3)** — with two divergent orchestrators writing canonical `contacts` directly, nothing proves intake and scan agree or that approval is the only write gate; this is the core correctness claim of Phases 1–2.
  3. **Green suite hides confirmed security bugs (P0-7/P0-8)** — the API-key leak (`app.py:106-112`), the `intake.py:78` NameError, and the broken dropzone all pass CI today; one strict-xfail test per bug turns the suite into a fix-ratchet instead of false assurance.
  *(Runner-up: zero PDF content tests — Scenario B rests entirely on `test_dispatch_pdf`, an extension check.)*
