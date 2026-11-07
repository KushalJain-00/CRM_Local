# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

[inferred from brief — no interview conducted; user instructed autonomous execution] Solo operators and sales/business-development users on Windows desktops who receive folders of spreadsheets, PDFs, text files and emails and need them converted into reliable, reviewable business contact records. Single-user, local-first. No multi-tenant or team use confirmed.

## Product Purpose

CRM_Local is a local-first CRM and universal business-information extraction platform: one application, one SQLite database, one universal intake, one extraction engine, one staged-contact workflow, one CRM workspace. It converts unstructured business information from six file formats (XLSX, XLS, CSV, PDF, TXT, EML) into structured, searchable, validated business records with full source provenance, staged for human review before entering the canonical CRM.

Success means: a user can drop a folder of mixed files, get every genuinely identifiable company/contact/email extracted with evidence, review and approve staged candidates, and work the results as a complete CRM — all offline for local tasks.

## Positioning

[inferred from brief] Local-first and offline-capable: no cloud services, no mandatory authentication, no remote frontend dependencies, no mandatory paid APIs. Deterministic extraction always works offline; external LLM enrichment is opt-in only. Evidence-backed extraction with mandatory human review distinguishes it from CRMs that push data to the cloud or auto-commit unverified AI output.

## Operating Context

- Windows desktop product packaged with PyInstaller + Inno Setup (CRM_Local.spec, CRM_Local.iss); browser-based frontend served by a local FastAPI app; SQLite persistence; localhost-only API.
- Reference repository `/home/kushal_jain/PROJECTS/CRM_Developer` (cloud Supabase CRM) is the source for CRM feature parity — its cloud architecture (Supabase auth, Postgres, Render/Vercel) is explicitly NOT migrated.
- Optional AI enrichment via OpenRouter, Groq, Gemini, OpenAI, DeepSeek, Anthropic, Ollama; Ollama supports fully local models. File text is never sent to an external provider without explicit configuration and user-visible awareness.
- Workflows: universal file dropzone, folder scanning/watching with processed-file ledger, field mapping with import templates, staged review with approval/merge/reject, enrichment, exports.

## Capabilities and Constraints

Confirmed by brief:

- Six source formats through one intake → one extraction engine → one unified staging system → canonical CRM (contacts, companies, emails, call logs).
- Two-layer extraction: Layer 1 deterministic local (always, offline); Layer 2 optional AI enrichment that fills gaps only — never overwrites populated local values, never invents, carries per-field evidence with confidence labels.
- Staging has three independent status dimensions: review (NEW/NEEDS_REVIEW/READY/APPROVED/REJECTED/DISMISSED), dedup (NOT_CHECKED/UNIQUE/EXACT_DUPLICATE/PROBABLE_DUPLICATE/CONFLICT), import (NOT_IMPORTED/NEW_CONTACT_CREATED/EXISTING_CONTACT_ENRICHED/IMPORT_FAILED). Import policies: Review First / Smart Import / Always Stage, user-selectable.
- CRM workspace: Dashboard, Import Center, Review Queue, Contacts (10,000+ records, server-side pagination), Companies (with merge), Emails (two-pane browser), Calls & Activities, Duplicates, Data Quality, Processing History, Reports & Exports (XLSX/CSV/PDF/VCF/ZIP, formula-injection protection), Settings (7 providers, secrets never exposed to browser JS), Help.
- Productivity: global search, command palette (Ctrl/Cmd+K), saved views, tags, notes, follow-ups, bulk operations, undo/recovery where feasible.
- Hard constraints: exactly one SQLite database; no Supabase/cloud auth/telemetry; no CDN or remote frontend dependencies; bundled local fonts/assets; **no graphs or charts anywhere** (KPIs, tables, ranked lists, timelines, status badges only); vanilla JS with native ES modules (no new framework); PyInstaller compatibility; WCAG 2.2 AA; prompt-injection resistance; export formula protection.
- Open decision (deferred to Phase 2): default import policy — brief says Smart Import only if validation+dedup safeguards are proven, else Review First.

## Brand Commitments

None specified. Name: "CRM_Local". Tone directives from brief (professional, calm, dense, precise, minimal, content-first, premium; avoid purple gradients, glassmorphism, emoji icons, oversized cards) are design guidance recorded here only as binding brief constraints, not a visual world — visual direction belongs to DESIGN.md (Phase 6).

## Evidence on Hand

- Target code: `/home/kushal_jain/PROJECTS/CRM_Local` (app.py, db.py, intake.py, llm.py, parse.py, pipeline.py, export.py, services/, static/, tests/)
- Reference code: `/home/kushal_jain/PROJECTS/CRM_Developer`
- `docs/IMPLEMENTATION_REPOSITORY_AUDIT.md` and `docs/LOCAL_PRODUCT_STATUS.md` (2026-11-06) — partially stale; e.g. LOCAL_PRODUCT_STATUS.md claims `services/extraction.py` exists but the file is absent. Verify all claims against source.
- `docs/USER_GUIDE.md`
- Master brief (2026-11-07 session): authoritative field tables (spec §3), master extraction system prompt and JSON contract (spec §6).
- Absence: the two supplied database diagrams were not attached to the session; a repo image search found none [pending confirmation]. Must not be fabricated — spec §3 field tables are the authority unless diagrams are located.

## Product Principles

1. Never invent information — every extracted value carries source evidence; humans approve before it becomes canonical.
2. One of everything — one app, one database, one intake, one extraction engine, one staging system, one provider manager.
3. Local-first — fully useful offline; external services are explicit opt-ins.
4. Preserve source truth — raw records, original emails, and provenance are never discarded; enrichment never silently overwrites populated fields (local-wins).
5. Dense, calm, content-first professional tool — precision over decoration; no charts.

## Accessibility & Inclusion

WCAG 2.2 Level AA required (brief §17): semantic HTML, keyboard navigation, visible focus, screen-reader announcements, accessible drawers/dialogs, reduced-motion support, accessible exports.
