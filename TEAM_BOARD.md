# TEAM_BOARD

**Orchestrator:** crm-orchestrator (this session)
**Mission:** Execute the master brief (2026-11-07) — transform CRM_Local into the universal CRM intelligence platform.
**Models:** primary `opencode/mimo-v2.6-flash-free`, fallback `opencode/beam-free`.

## Ground rules

- One accountable owner per file; never edit a file another active specialist owns.
- No commits or pushes without user authorization. No destructive DB operations without backup + verification.
- Investigators are read-only except their assigned doc(s).
- Verify every claim against source code — `docs/LOCAL_PRODUCT_STATUS.md` and `docs/IMPLEMENTATION_REPOSITORY_AUDIT.md` (2026-11-06) are hypotheses with known errors (e.g. phantom `services/extraction.py`).
- Bounded loops: max 2 focused correction attempts per blocker, then escalate here with evidence.
- Concurrency cap: 2–3 concurrent specialists (free-model capacity rule, brief §14.3).

## Coordination files

Live now: `TEAM_BOARD.md`, `TASK_LOG.md`, `DECISIONS.md`.
Created when first real content lands: `INTERFACE_CONTRACTS.md` (Phase 1 service contracts), `DEPENDENCIES.md` (packaging assessment), `SKILL_USAGE.md` (design phase skill usage).

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 0 | Repo/schema audit + 5 planning docs | **COMPLETE** — all 5 brief docs + 4 supplementary; 6/8 investigations done (backend+devops docs in R3) |
| 1 | Data & extraction foundations | **IN PROGRESS** — DB migration train + extraction modules dispatched in R3; security P0 set queued (D-028) |
| 2 | Universal staging workflow | NOT STARTED |
| 3 | Core CRM functionality | NOT STARTED |
| 4 | Extraction & import experience | NOT STARTED |
| 5 | Email intelligence & data management | NOT STARTED |
| 6 | Advanced UI/UX (ui-ux-pro-max + frontend-design) | NOT STARTED |
| 7 | Independent QA & security | NOT STARTED |
| 8 | Packaging & release | NOT STARTED |

## Phase 0 deliverables

| Doc | Owner (Round) | Status |
|---|---|---|
| docs/CRM_FEATURE_PARITY.md | systems-architect (R1) | ✅ DONE — 383 lines, 42-row matrix, placement map |
| docs/STAGED_CONTACT_ARCHITECTURE.md | database-engineer (R1) | ✅ DONE — 633 lines, full DDL + migration plan |
| docs/EXTRACTION_FIELD_MATRIX.md | extraction-engineer (R1) | ✅ DONE |
| docs/ADVANCED_EXTRACTION_SPEC.md | extraction-engineer (R1) | ✅ DONE |
| docs/ACCEPTANCE_SCENARIOS.md | orchestrator (from brief §16) | ✅ DONE — verbatim scenarios A–G |
| docs/DESIGN_RESEARCH.md | frontend-engineer (R2) | ✅ DONE — 28-row findings table + AA-checked visual direction (D-031) |
| docs/SECURITY_REVIEW.md | security-engineer (R2) | ✅ DONE — 14 findings (2H/3M/9L); SEC-01 widened; P0 set → D-028 |
| docs/QA_ACCEPTANCE_PLAN.md | qa-engineer (R2) | ✅ DONE — 58/58 baseline, 57-step A–G matrix (24 partial / 33 none) |
| docs/INTERFACE_CONTRACTS.md | backend-engineer (R3) | DISPATCHED — doubles as deferred board |
| docs/DEPENDENCIES.md | devops-engineer (R4) | QUEUED — doubles as deferred board |
| SKILL_USAGE.md | frontend-engineer (R2) | ✅ DONE — both mandatory skills evidenced (6 search.py invocations, adopted/rejected lists) |

## Round 1 consolidated findings (2026-11-07, 3 specialists, sessions ses_e4cdd9…3m/4t/KC)

1. **Two competing orchestrators** — `pipeline.py` (folder scan) and `intake.py` (dropzone) diverge on mapping, dedup, and destination; both upsert directly into canonical `contacts`. Violates brief §13 one-of-everything. (Confirmed independently by architect + extraction engineer.)
2. **Unified staging (spec §4) does not exist** — `eml_contacts` is a parallel EML-only table; no review/import status dimensions, no raw rows, no conflict/merge/audit tables; 6 of 11 tables are dead (zero writers).
3. **Confirmed secrets leak** — `GET /api/config` returns `chain[].api_key` to browser JS (`app.py:106-112`), in BOTH repos. (D-011 fixes.)
4. **Silent data loss** — 14+ of 25 mapping types discarded (`parse.py:72,174-188`); emails without contacts dropped (`pipeline.py:145-147`); intake EML path stores no email; provenance columns populated in 0 rows; live DB missing the FK that `db.py:65` declares (schema drift).
5. **Latent bugs** — `intake.py:78` calls nonexistent `llm.extract` (NameError behind the empty chain); dropzone transport broken (`app.js:114` bare names → `os.path.exists` fail); name-only auto-merge (`db.py:384-387`) violates same-name≠same-person; `filterContacts`/`exportContacts` referenced but undefined (`index.html:80,86`).
6. **Prior audits stale in BOTH directions** — phantom `services/extraction.py` claimed; committed work (9-view frontend, unified DB) understated. D-001 stands.
7. **Reference is weaker than the brief on ~10 rows** (no server-side list, companies view, saved views, tags, global search, command palette) — those are net-new builds, not ports.

**Top risks carried forward:** staging schema freeze timing (resolved by D-006/D-014 before Phase 1); ES-module migration blast radius on inline-onclick UI; new deps (`reportlab`, `python-multipart`) need `CRM_Local.spec` hiddenimports + CI verification (D-009/D-013, R3 devops).

## Round 2 results (2026-11-07)

- **Security (14 findings: 0C/2H/3M/9L):** SEC-01 key leak CONFIRMED and widened (all four config/settings endpoints leak `chain[].api_key`, `app.py:106-112,125,160-172`); SEC-02 stored XSS via unescaped `innerHTML` (`app.js:253,268,86,124`) chains into SEC-01; SEC-03 no Origin/Host validation (CSRF rewrite + DNS-rebinding key reads, static evidence); column-name SQLi in `PATCH /api/contacts` (`db.py:503`) REFUTES prior "parameterized everywhere" claim; `config.json` 0644; scan path uncapped; magic bytes/size caps PARTIAL (intake only); log redaction PARTIAL. Prior-claim verdicts: loopback, headers, openapi-off, no-CDN, no-telemetry, no-secrets-in-git = CONFIRMED. → D-028.
- **QA:** baseline `python3 -m pytest -q` (venv lacks pytest) → **58/58 pass, 181.71s, Python 3.14.7/pytest 9.1.1 vs CI 3.11/3.12 skew**. Scenario coverage: 57 steps → 24 partial / 33 none; F2 BLOCKED-ENV (Windows). P0 gaps: no migration-verification tests, no write-path single-ness tests, green suite hides known bugs → fix-ratchet adopted (D-029). Stale-doc flag: ADVANCED_EXTRACTION_SPEC §7.4 vs D-024 → supersede note pending.
- **Design:** websearch unavailable (HTTP 402) — research used direct fetches + skill local data, honestly labeled (docs) vs (gallery). Direction accepted → D-031. Risks: ES-module blast radius, net-new surfaces with no backend, Analytics deletion vs placeholder KPIs.

## Round 3 dispatch (2026-11-07) — 3 concurrent, disjoint file ownership

1. **database-engineer (IMPLEMENT)** — Phase 1 migration train per D-030: additive subset only (v5c backfills, v6 contacts rebuild with backup+counts, `staged_contacts` + relationships + indexes + CHECK enums, receiver columns) + migration verification tests. Owns `db.py`, `tests/test_migrations.py` (new). Live-DB apply with step-0 backup.
2. **extraction-engineer (IMPLEMENT)** — Phase 1 extraction foundations as NEW modules only: `services/prompts/contact_extraction.py` (master prompt §6.1 + source extensions), contract validator (`crm-extraction.v1`), unified validation service (7 issue categories), shared dedup engine (D-006/D-021/D-023 semantics) + unit tests. Owns new files under `services/` + new test files. NO wiring into intake/pipeline (Phase 2), NO edits to byte-identical shared services.
3. **backend-architect (INVESTIGATE)** — `docs/INTERFACE_CONTRACTS.md`: complete HTTP surface spec for all workspace areas (parity placement map + brief §9/§11/§12), request/response shapes, server-side pagination contract, settings surface (D-011/D-028), intake transport (D-009), jobs/cancellation, Phase-2 review-queue endpoints, error model. Read-only.

## Round 3 results (2026-11-07) — CLOSED

All 3 dispatched tasks green: db.py migration train v2,3,4,5,6,9,10 (+16 tests, live-DB gate, rollback_sql, `_migration_log` per D-030); services/prompts + contract/validation/dedup (+40 tests, phone_key reused); `docs/INTERFACE_CONTRACTS.md` (86 endpoints, 24 Phase-2-critical, 8 open questions incl. Q1 manual-POST writer conflict with D-007). QA baseline rerun **211 passed**. Uncommitted; live DB untouched.

## Round 4 dispatch (2026-11-07) — 2 concurrent, disjoint ownership

1. **security-reviewer (IMPLEMENT)** — remaining P0: mask API keys on all four settings endpoints (D-028: list/update per-credential plus any config-read) with masked-id semantics from `docs/INTERFACE_CONTRACTS.md` §5; `esc()` the four `app.js` sinks (253, 268, 86, 124); Origin/Host middleware (SEC-03, first-invalid rejection + test); fix `intake.py:78` NameError (import too narrow for `except NameError`); `config.json` → 0600 verified; SEC-10 mirror of byte-identical fixes to CRM_Developer. Owns `app.py`, `app.js`, `intake.py`, `config.py` (perms), mirrored files in CRM_Developer.
2. **devops (INVESTIGATE)** → `docs/DEPENDENCIES.md`: runtime vs packaging (PyInstaller hiddenimports for reportlab/python-multipart) vs test deps, dupes, CI version matrix (3.11/3.12 vs local 3.14 skew). Owns that doc only.

**Round 4 results (closed 2026-11-07):** security P0 all FIXED (SEC-01/02/03/07/09/11/13 + SEC-10 mirrored byte-identical to CRM_Developer; SEC-04/05/06 deferred to Phase 4 with ratchets intact); suite **231 passed, 6 xfailed**; config.json 0600. Devops: docs/DEPENDENCIES.md (gaps: venv lacks pytest, pydantic undeclared, CI/local skew). D-032 resolved all 8 contract questions. QA ratchet: tests/test_ratchet.py (7 strict xfail).

**Live migration apply: DEFERRED by user decision (2026-11-07)** — 3-day-old server PID 9106 left running; `CRM_APPLY_MIGRATIONS=1` apply waits for an explicit user go-ahead. Code/tests proceed on fresh test DBs only; never assume the live DB has v2+ schema.

## Phase 2 — Round P2-1 dispatch (2026-11-07) — 2 concurrent, disjoint ownership

1. **backend-specialist A (IMPLEMENT) — data layer:** v7 migration `eml_contacts` → VIEW (D-006/D-030, checksummed + rollback, gated like the rest — DO NOT apply to live DB) + D-007 write-path redirect (intake.py/pipeline.py direct canonical upserts → `staged_contacts`) + `services/approval.py` core (approve with local-wins + before-image audit D-014, reject/dismiss/restore, conflict-resolve, merge-into-existing, approve-selected, approve-all-safe = READY+UNIQUE only per D-032 Q4) + tests. Owns: `db.py`, `intake.py`, `pipeline.py`, `services/approval.py` (new), `tests/test_migrations.py`, `tests/test_approval.py` (new). Byte-identical shared files: mirror or don't touch. No HTTP layer (P2-2).
2. **backend-specialist B (IMPLEMENT) — D-010 route split:** mechanical move of EXISTING routes into `api/` package per INTERFACE_CONTRACTS §2.1 (system, settings, intake, jobs, contacts, reports) + retire `GET/POST /api/config` → hard 410 per catalogue #5/6 (D-011); `app.py` keeps exactly the §2.1 "stays" list (SEC-03 middleware, headers, startup, index, static, guard, main). Update `CRM_Local.spec` hiddenimports + any CI paths; adjust config-endpoint tests to 410 WITHOUT weakening settings masking. Owns: `app.py`, `api/**` (new), `CRM_Local.spec`, `.github/workflows/*` (path fixes only), tests of moved routes. NO edits to db.py/intake.py/pipeline.py/services (A owns those concurrently).

**Then P2-2:** ★ staging endpoints + providers/settings-mode + real jobs + D-009 multipart intake + review-queue UI; then P2-3 QA acceptance pass.

**Halt condition:** any failing test, ownership violation, 2 failed correction attempts, or deviation from DECISIONS.md

**Halt condition:** any failing test, ownership violation, 2 failed correction attempts, or deviation from DECISIONS.md

## File ownership

- Orchestrator: TEAM_BOARD.md, TASK_LOG.md, DECISIONS.md, PRODUCT.md, this board only.
- Each specialist: exactly the doc(s) assigned in its dispatch.
- Code files: owned per implementation task when Phase 1+ begins — record here before any edit.
