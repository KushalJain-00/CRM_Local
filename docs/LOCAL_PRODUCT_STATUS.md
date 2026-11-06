# CRM_Local — Product Status Report

**Date:** 2026-11-06
**Status:** Implementation in progress — Phase 2 (database) complete, Phase 3-8 remaining

---

## 1. Feature Classification

### Fully Implemented and Integrated in CRM_Local

| Feature | Files | Evidence |
|---|---|---|
| Unified 11-table SQLite schema | `db.py` | All 11 tables created; `init()` runs migration from eml.db; 22 tests pass |
| FK enforcement | `db.py` connect() | `PRAGMA foreign_keys=ON` on every connection |
| Migration from eml.db | `db.py` `_migrate_eml_data()` | 47 eml_contacts + 60 emails + 62 processed_files migrated |
| Provenance columns | `db.py` contacts table | source_file, source_row, extraction_run_id, field_origin, email_key, phone_key, whatsapp, products_misc |
| Shared services (synced) | `services/eml_processor.py`, `services/eml_dedup_rules.py`, `services/parser.py` | Byte-identical with CRM_Developer |
| Prompt injection wrapping | `services/eml_processor.py` | build_llm_prompt wraps content; system prompt has data-only instruction |
| merge_fields local-wins | `services/eml_processor.py` | Local values preserved, AI fills gaps |
| Shared phone_key() | `services/eml_dedup_rules.py` | phone_key() function added |
| LLM output validation | `llm.py` parse_json() | Field length/format validation |
| Gemini model validation | `llm.py` _call() | Regex validation before URL construction |
| Formula injection sanitization | `export.py` | _sanitize() prefixes risky cells |
| Security headers | `app.py` | X-Content-Type-Options, X-Frame-Options, Referrer-Policy |
| openapi_url=None | `app.py` | OpenAPI schema disabled |
| 6 extraction adapters | `services/adapters/` | Xlsx, Xls, Csv, Pdf, Txt, Eml adapters + registry |
| ExtractionResult/NormalizedContact | `services/adapters/__init__.py` | Dataclasses defined |
| Universal extraction orchestrator | `services/extraction.py` | run_extraction(), run_batch() |
| Folder watching | `pipeline.py` | _watch_loop, start_watch/stop_watch |
| Processed-file ledger | `db.py` | is_processed, mark_processed |
| Native folder dialogs | `app.py` | /api/pick-folder (tkinter) |
| Local Ollama support | `llm.py` | Ollama provider in PROVIDERS |
| PyInstaller compatibility | `app.py` | Windowed exe guard, _MEIPASS |
| Styled Excel export | `export.py` | openpyxl with styled headers |
| Autostart | `app.py` | Windows Startup folder .cmd |

### Implemented but Not Integrated

| Feature | Status | Notes |
|---|---|---|
| Universal intake endpoint (POST /api/intake) | MISSING | Not yet implemented in CRM_Local |
| Centralized settings API | MISSING | Still uses /api/config |
| Job status/cancellation | MISSING | Not yet implemented |
| Adapter integration in pipeline | MISSING | pipeline.py still uses old parsing |
| Provenance population in pipeline | MISSING | Not yet wired |
| Security headers | ✅ DONE | Added to app.py |
| Rate limiting | MISSING | Not yet implemented |

### Available Only in CRM_Developer

| Feature | CRM_Developer File | Adaptation Needed |
|---|---|---|
| data_access.py (C-01) | services/data_access.py | Adapt for sync sqlite3 |
| intake.py | api/intake.py | Adapt for local mode |
| settings.py | api/settings.py | Adapt for local mode |
| Security headers middleware | main.py | ✅ Already adapted |
| CI workflow | .github/workflows/ci.yml | Add to CRM_Local |
| .env.example | .env.example | Adapt for local |

### Missing

| Feature | Priority | Notes |
|---|---|---|
| Universal intake endpoint | P1 | Need to create /api/intake |
| Centralized settings API | P1 | Need to create /api/settings |
| Job status/cancellation | P2 | Need to create /api/jobs |
| 14-view CRM workspace | P1 | Frontend expansion needed |
| Accessibility (WCAG 2.2 AA) | P1 | Frontend work needed |
| Hash-based routing | P2 | Frontend work needed |
| Test coverage ≥80% | P1 | Need more tests |
| Windows installer verification | P1 | Need CI verification |
| Adapter tests | P2 | Need to port tests |

### Blocked

| Feature | Blocker |
|---|---|
| Windows installer testing | No Windows environment available |
| TLS verification for Supabase | N/A (local-only, no cloud) |

## 2. Current Test Status

- CRM_Local: 22 tests passing (db, export, llm, parse, pipeline)
- CRM_Developer: 77 tests passing (55 original + 22 new)

## 3. Next Steps

1. Implement universal intake endpoint in app.py
2. Implement centralized settings API in app.py
3. Add security headers (done)
4. Expand frontend to 14 views
5. Add tests for new functionality
6. Verify packaging

---

*End of LOCAL_PRODUCT_STATUS.md*