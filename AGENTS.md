# AGENTS.md — Guidelines for AI Agents Contributing to CRM Local

This file provides agent-specific conventions, checkpoints, and quality gates for AI agents working on the CRM Local project. Read this before starting any task.

## ⚠️ MANDATORY: Read DECISIONS.md First

**Always** read `DECISIONS.md` before starting any task. Recent rulings constrain what changes are permissible. The file is append-only — new decisions are never deleted.

Recent critical decisions (2026-11-07):
- **D-011**: `/api/config` retired → use `/api/settings`; mask `api_key` on ALL four endpoints
- **D-030**: Migration train split — Phase 1 ships additive subset; v7 deferred to Phase 2
- **D-028**: Security P0 set — mask api_key on ALL config/settings endpoints; add server-side sanitizer; Origin/Host validation
- **D-029**: Adopt QA's fix-ratchet — every confirmed-but-unfixed bug gets `xfail(strict=True)`; green suite must not hide known defects

## 🛑 Non-Negotiable Constraints

| Constraint | Reason | Enforced By |
|---|---|---|
| **No auto-migrations on startup** | D-030 gate + data safety | `db.py:run_migrations()` — checks `CRM_APPLY_MIGRATIONS=1` + live DB detection |
| **api_key must never leak** | SEC-01 / D-011 | `config.py:_mask_chain()`, `api/settings.py:_mask_chain()`, `api/settings.py:get_settings()` |
| **No charts/graphs anywhere** | Brief hard constraint | `PRODUCT.md` principle 5; `INTERFACE_CONTRACTS.md` |
| **WCAG 2.2 AA compliance** | Brief §17 | Frontend standards; accessibility audit |
| **One SQLite database only** | Architecture constraint | `db.py:_UNIFIED_DB = "crm.db"` |
| **LLM output validated against contract** | Data integrity | `services/contract.py:validate_extraction_result()` |
| **Dedup keys use shared normalizers** | Consistency | `services/keys.py` |
| **Header byte caps are SEC-10** | Security | `services/eml_processor.py` + mirror to CRM_Developer |
| **config.json perms: 0600 on POSIX** | Secrets protection | `config.py:_private()` + `lock_down()` |
| **config.json never exposed to browser JS** | Secrets leak (D-011) | `api/settings.py` masks all keys; `/api/config` retired |

## 🔧 Agent Workflow

### 1. Startup Checklist

Before writing any code:

- [ ] Read `DECISIONS.md` — note any rulings that affect your task
- [ ] Run `pytest -q` — ensure test suite is green before your changes
- [ ] Check `CONTEXT.md` for domain model, field definitions, and key constants
- [ ] Check `Handover.md` for architectural patterns and recently decided conventions

### 2. Code Change Checklist

For every code change:

- [ ] **Tests pass**: `venv/bin/python -m pytest -q` — all existing tests still green
- [ ] **No api_key leakage**: Search your diff for any raw `api_key` strings; ensure they go through `_mask_chain()`
- [ ] **DB changes gated**: If touching migrations, remember `CRM_APPLY_MIGRATIONS=1` requirement
- [ ] **API contracts**: If adding/removing routes, check `INTERFACE_CONTRACTS.md` §2.1
- [ ] **Dedup key consistency**: If adding new dedup logic, use shared normalizers from `services/keys.py`
- [ ] **Prompt format**: If modifying extraction prompts, follow `build_prompt()` pattern from `services/prompts/contact_extraction.py`
- [ ] **Header caps**: If modifying `services/eml_processor.py`, mirror byte-for-byte to CRM_Developer
- [ ] **No new charts**: Verify no `chart-*` ids or Canvas/Plotly/D3 additions

### 3. Task-Specific Guidelines

#### Adding a New File Format Adapter

Follow the pattern in `services/adapters/`:
- Implement `can_handle(path) → bool` — check file extension
- Implement `extract(path) → ExtractionResult` — return `contacts` list + `adapter` name + `local_only=True`
- Add adapter name to the intake routing if needed
- Register in any discovery/lookup tables

#### Adding a New Extraction Field

1. Add the field to the `EXTRACTION_CONTRACT` in `services/prompts/contact_extraction.py`
2. Add it to the relevant model (`NormalizedContact`, `StagedContactIn`, etc.)
3. Add extraction guidance to the appropriate `SOURCE_EXTENSIONS` entry
4. Add validation in `services/validation.py` if it's a format-sensitive field (email, phone, pincode, website, company, position/designation, industry)
5. Add the column to the SQLite schema in `db.py:_SCHEMA_UNIFIED` if not already present
6. Add the field to `staged_contacts` DDL if it's staging-relevant
7. Run `pytest -q` to verify nothing is broken

#### Modifying the Migration Train

1. Remember: `run_migrations()` is gated by `CRM_APPLY_MIGRATIONS=1`
2. App startups, tests, and CI must **never** restructure production data by accident
3. Each migration runs in its own explicit transaction with rollback on failure
4. Register new migrations via `_Migration` class with version, name, fn, rollback_sql, fk_off flag
5. Update `CURRENT_MIGRATION_VERSION` if extending beyond v10
6. Add rollback SQL for reversibility
7. Test with `CRM_APPLY_MIGRATIONS=1` set and not set

#### Adding/Modifying API Routes

1. Check `INTERFACE_CONTRACTS.md` §2.1 for route contracts and conventions
2. Routes live in `api/` package; composition root in `app.py`
3. All routes must return JSON responses; errors use `HTTPException` with appropriate status codes
4. Provider data must never expose raw `api_key` — go through `_mask_chain()`
5. If adding a new route, add it to the appropriate `api/*.py` file and include it in `api/__init__.py::__all__`

#### Fixing Security Issues (SEC-01 through SEC-10)

1. **SEC-01 (api_key masking)**: Search for any endpoint that returns config/chain data; ensure `api_key` values go through `_mask_chain()` or `MASKED_KEY = "********"`
2. **SEC-03 (Origin/Host validation)**: Loopback-only middleware in `app.py`; foreign Origins rejected before Host considered
3. **SEC-05 (bytes not paths)**: Universal intake receives bytes, never filesystem paths
4. **SEC-06 (prompt caps)**: MAX_CONTENT_CHARS=8000, UNTRUSTED markers, header byte caps
5. **SEC-07 (EML header caps)**: Mirror byte-for-byte to CRM_Developer if modifying `services/eml_processor.py`
6. **SEC-08 (LLM banned keys)**: BANNED_DB_KEYS check in `services/contract.py:validate_extraction_result()`
7. **SEC-09 (config.json perms)**: `config._private()` + `config.lock_down()` at startup

## 🚦 Quality Gates

### Before Claiming Work is Complete

1. **`pytest -q` all tests pass** — no regressions
2. **`DECISIONS.md` checked** — no recent ruling contradicts your change
3. **`api_key` leakage searched** — no raw keys in diff
4. **Security review for DB/API changes** — masked keys, origin validation, perms
5. **No new charts/graphs** — brief constraint
6. **Agent self-evaluation** — complete the `agent-self-evaluation` skill before marking work done

### Test Expectations

- `venv/bin/python -m pytest -q` must pass with your changes
- If you add new functionality, add new tests or ensure existing tests cover the code path
- Migrations: test both with `CRM_APPLY_MIGRATIONS=1` set and not set
- API: test error status codes, response shapes, masking

## 📚 Reference Documents (Read These)

| Document | Purpose |
|---|---|
| `DECISIONS.md` | All architectural & product decisions (append-only) |
| `CONTEXT.md` | Domain model, field definitions, technical context |
| `Handover.md` | Current state, recent decisions, open questions |
| `PRODUCT.md` | Product overview, positioning, constraints, principles |
| `INTERFACE_CONTRACTS.md` | API route contracts ( §2.1) |
| `services/prompts/contact_extraction.py` | Master prompt + shared JSON contract |
| `db.py` | Unified schema, migration train, dedup keys |
| `services/contract.py` | Extraction result validation |
| `services/validation.py` | Post-extraction field validator |
| `services/eml_processor.py` | EML parsing + SEC-10 header caps |
| `requirements.txt` / `requirements-dev.txt` | Dependencies |

## 🔍 Common Pitfalls (Check Before Committing)

| Pitfall | How to Avoid |
|---|---|
| **Forgetting `_mask_chain()`** on provider chain responses | Search diff for `api_key`; ensure it passes through masking |
| **Applying migrations on startup** | Remember `CRM_APPLY_MIGRATIONS=1` gate; `db.py` enforces it |
| **New chart/graph component** | Brief hard constraint — use tables/status badges instead |
| **LLM emitting DB-owned fields** | `validate_extraction_result()` checks BANNED_DB_KEYS |
| **Dedup keys computed differently** | Use shared normalizers from `services/keys.py` |
| **`config.json` not 0600 on POSIX** | `config.lock_down()` called at app startup (`app.py:163`) |
| **`/api/config` still in code** | Retired per D-011 — use `/api/settings` only |
| **Origin validation bypassed** | Loopback middleware in `app.py:42-63` — foreign Origins always rejected |
| **Sending filesystem paths to LLM** | Universal intake sends bytes only (D-009 / SEC-05) |

## 🆘 Getting Help

If you're stuck:

1. **Run `pytest -q`** — failing tests often indicate the right fix area
2. **Check `DECISIONS.md`** — recent rulings may constrain or guide your change
3. **Search for similar patterns** in the codebase — CRM Local has consistent patterns
4. **Review `Handover.md`** — open questions and recent decisions
5. **If still stuck**, ask the user to clarify the task scope

## 📝 Agent Self-Evaluation

Before marking any task complete, complete a self-evaluation using the `agent-self-evaluation` skill. Rate your output on 5 axes — accuracy, completeness, clarity, actionability, conciseness — with concrete evidence per criterion. This is mandatory before claiming work is complete.

---

**Last generated**: 2026-11-07

**This file is part of the ECC (Extensible Codebase Configuration) system.** It should survive across sessions via `memory_save` or `session_end`. If it feels stale, run `memory_recall` with query "AGENTS.md" to check for updates.