# IMPLEMENTATION REPOSITORY AUDIT

**Date:** 2026-11-06
**Auditor:** crm-orchestrator

---

## 1. Repository Comparison

| Aspect | CRM_Developer (reference) | CRM_Local (target product) |
|---|---|---|
| **Path** | `/home/kushal_jain/PROJECTS/CRM_Developer` | `/home/kushal_jain/PROJECTS/CRM_Local` |
| **Purpose** | Cloud dashboard (reference) | Windows desktop (final product) |
| **Auth** | Supabase JWT | None (loopback only) |
| **Database** | Supabase Postgres / SQLite dev | Two SQLite files (crm.db + eml.db) |
| **Frontend** | 14 SPA views, 1,994-line app.js | 3 views (Run/Contacts/Settings), 570-line app.js |
| **Packaging** | Render + Vercel | PyInstaller + Inno Setup |
| **LLM** | 1 attempt/provider, 45s budget | 3 attempts, 120s timeout, +Ollama |
| **Git status** | 14 modified + 12 new files (all uncommitted) | Clean (no modifications) |

## 2. Feature Implementation Status

| Feature | CRM_Developer | CRM_Local | Migration Needed |
|---|---|---|---|
| Unified 11-table schema | ✅ Implemented | ❌ 2 separate DBs (crm.db + eml.db) | YES — merge into one DB |
| FK enforcement | ✅ PRAGMA foreign_keys=ON | ❌ Not enabled | YES |
| TLS verification | ✅ CERT_REQUIRED by default | N/A (local only) | NO |
| Prompt injection wrapping | ✅ build_llm_prompt wraps content | ❌ No wrapping | YES — adapt |
| Gemini model validation | ✅ Regex validation | ❌ Not present | YES — adapt |
| merge_fields local-wins | ✅ Fixed | ❌ AI may overwrite (check needed) | VERIFY + FIX |
| CSV formula injection | ✅ Sanitized | ❌ Not sanitized | YES — adapt |
| Magic bytes validation | ✅ Implemented | ❌ Not present | YES — adapt |
| openapi_url=None | ✅ Implemented | ❌ Not set | YES — adapt |
| Log redaction | ✅ Implemented | ❌ Not present | YES — adapt |
| Auth identity binding | ✅ Implemented | N/A (no auth) | NO (local mode) |
| Proxy rate limiting | ✅ Implemented | N/A (loopback only) | NO (local mode) |
| Data access layer (C-01) | ✅ services/data_access.py | ❌ Routers own ORM | YES — adapt |
| Extraction adapters (6) | ✅ services/adapters/ | ❌ Monolithic parser | YES — adapt |
| NormalizedContact/ExtractionResult | ✅ Created | ❌ Not present | YES — adapt |
| Universal intake (POST /api/intake) | ✅ api/intake.py | ❌ Separate scan endpoints | YES — adapt |
| Settings API | ✅ api/settings.py | ❌ Config via /api/config | PARTIAL — adapt |
| Provenance tracking | ✅ extraction_run_id, field_origin | ❌ Not present | YES — adapt |
| Adapter tests | ✅ 16 tests | ❌ 5 test files (db, export, llm, parse, pipeline) | YES — add |
| Prompt injection tests | ✅ 8 tests | ❌ Not present | YES — add |
| CI workflow | ✅ .github/workflows/ci.yml | ✅ .github/workflows/windows-build.yml | PARTIAL — add test stage |
| .env.example | ✅ Created | ❌ Not present | YES — adapt |
| Health check | ✅ /health endpoint | ✅ /api/status | PARTIAL — add /health |
| Dependency pinning | ✅ Pinned | ❌ Unpinned (fastapi==0.111.0 etc.) | PARTIAL — already pinned |
| Security headers | ✅ Middleware | ❌ Not present | YES — adapt |
| Accessibility | ✅ Skip link, ARIA, focus-visible | ❌ Basic | PARTIAL — adapt |
| Hash routing | ✅ Added to app.js | ❌ Not present | PARTIAL — adapt |
| Phone normalization parity (G14) | ✅ phone_key() added | ❌ phone_key() strips 91 prefix | VERIFY — may need update |
| merge_fields local-wins | ✅ Fixed | ❌ Need to verify | VERIFY |

## 3. What CRM_Local Already Has (Preserve)

- Folder watching with processed_files ledger
- Native folder dialogs (tkinter)
- Local Ollama provider support
- PyInstaller compatibility (windowed exe guard)
- Inno Setup installer (CRM_Local.iss)
- Windows build CI (windows-build.yml)
- 3-view UI (Run/Contacts/Settings) with 570-line app.js
- 5 test files (db, export, llm, parse, pipeline)
- Processed-file idempotency (scan by path/size/mtime)
- EML sort by Date header
- Contact enrichment (upsert_contact fills empty fields only)
- DedupIndex with email/phone/name matching
- Styled Excel export (openpyxl)
- Native folder picker (180s timeout)
- Autostart (Windows Startup folder)

## 4. Migration Plan for CRM_Local

### Phase A: Database consolidation (P2 equivalent)
1. Merge crm.db + eml.db into single crm_local.db
2. Implement 11-table unified schema (from CRM_Developer db/models.py)
3. Enable FK enforcement (PRAGMA foreign_keys=ON)
4. Add provenance columns (source_file, source_row, extraction_run_id, field_origin, email_key, phone_key, whatsapp, products_misc)
5. Create _migration_log table for versioned migrations
6. Migrate existing data from both DBs
7. Implement backup/restore

### Phase B: Security fixes (adapt from CRM_Developer)
1. Prompt injection wrapping in eml_processor.py (shared service — update both)
2. Gemini model validation in llm_router.py (adapt from CRM_Developer)
3. Formula injection sanitization in export.py
4. Magic bytes validation for file uploads
5. Log redaction in app.py
6. openapi_url=None (if applicable)

### Phase C: Extraction engine (adapt from CRM_Developer)
1. Create services/adapters/ directory with 6 adapters
2. Implement NormalizedContact + ExtractionResult
3. LLM output validation (field lengths/formats)
4. Shared phone_key() function
5. Provenance tracking in pipeline.py

### Phase D: Universal intake
1. Create POST /api/intake endpoint
2. Implement job status/cancellation
3. File count/size caps
4. Universal file classification

### Phase E: Centralized settings
1. Update /api/config to support chain validation
2. Add /api/settings endpoints
3. Chain entry validation (provider allow-list, model regex)

### Phase F: CRM workspace
1. Expand static/index.html to include all 14 views
2. Add hash-based routing
3. Add accessibility (ARIA, focus-visible, reduced-motion)
4. Add cold-start retry to all fetches

### Phase G: Security + reliability
1. Security headers middleware
2. Test coverage expansion
3. Migration/integrity tests

### Phase H: Packaging
1. Update .github/workflows/windows-build.yml with test stage
2. Create .env.example (adapted for local)
3. Pin dependencies
4. Verify clean install + upgrade

## 5. Shared Services Compatibility

The shared services (eml_processor.py, eml_dedup_rules.py, parser.py) must remain byte-identical between CRM_Developer and CRM_Local.

CRM_Developer has updated:
- eml_processor.py: build_llm_prompt wraps content; merge_fields local-wins
- eml_dedup_rules.py: phone_key() added
- llm_router.py: ChainEntry base_url/enabled, model validation, cache key fix, DeepSeek endpoint, output validation

CRM_Local must receive these same changes (adapted for local context).

## 6. What Must NOT Be Migrated

- Supabase Auth (JWT) — local uses loopback only
- Supabase Postgres — local uses SQLite
- Render/Vercel config — local uses PyInstaller/Inno
- Cloud rate limiting (proxy-aware) — local uses simple rate limiting
- Multi-tenant data model — local is single-user
- Cloud-specific CORS (null origin) — local uses loopback only

## 7. What Must Be Preserved in CRM_Local

- Folder watching with processed_files ledger
- Native folder dialogs (tkinter)
- Local Ollama provider
- PyInstaller compatibility (windowed exe guard, _MEIPASS)
- Inno Setup installer
- Windows build CI
- 3-view UI (expand to 14 views)
- 5 test files (expand with new tests)
- Processed-file idempotency
- EML sort by Date header
- Contact enrichment (upsert_contact fills empty fields only)
- DedupIndex with email/phone/name matching
- Styled Excel export (openpyxl)
- Native folder picker (180s timeout)
- Autostart (Windows Startup folder)

## 8. Feature-by-Feature Comparison

See section 2 above. Summary:

- **CRM_Developer has 14 files modified + 12 new files** with security fixes, adapter architecture, data access layer, provenance tracking, universal intake, settings API, and accessibility improvements.
- **CRM_Local has 0 modifications** — it's in its original state.
- **Migration is required** to bring the good improvements from CRM_Developer into CRM_Local, adapted for local-first architecture.

## 9. Recommended Execution Order

1. **Audit complete** (this document)
2. **Phase A: Database consolidation** (merge 2 DBs into 1, enable FKs, add provenance columns)
3. **Phase B: Security fixes** (prompt injection, model validation, formula injection, magic bytes, log redaction, openapi_url)
4. **Phase C: Extraction engine** (adapters, NormalizedContact, LLM validation, phone_key, provenance)
5. **Phase D: Universal intake** (POST /api/intake, job status/cancellation)
6. **Phase E: Centralized settings** (settings API, chain validation)
7. **Phase F: CRM workspace** (expand UI to 14 views, accessibility, routing)
8. **Phase G: Security + reliability** (security headers, tests, coverage)
9. **Phase H: Packaging** (CI, .env.example, pinning, clean install test)

Each phase must be verified before proceeding to the next.

## 10. What Must NOT Be Claimed

- CRM_Local is NOT complete. It has received NO implementation changes.
- The 77 passing tests are in CRM_Developer, not CRM_Local.
- The 11-table schema is in CRM_Developer, not CRM_Local.
- The extraction adapters are in CRM_Developer, not CRM_Local.
- POST /api/intake is in CRM_Developer, not CRM_Local.
- The settings API is in CRM_Developer, not CRM_Local.

CRM_Local must be independently implemented and verified.