# Interface Contracts — Phases 2–6

**Status:** binding contract for backend + frontend work in Phases 2–6.
**Scope:** every HTTP surface this repository will expose, its wire format, and how it maps onto the current `app.py` (the only route file today, 18 routes).
**Binding inputs:** `DECISIONS.md` (D-006…D-031), `docs/CRM_FEATURE_PARITY.md`, `docs/STAGED_CONTACT_ARCHITECTURE.md`, `docs/ADVANCED_EXTRACTION_SPEC.md`, `docs/SECURITY_REVIEW.md`, `docs/QA_ACCEPTANCE_PLAN.md`, `PRODUCT.md`.
**Owner:** backend engineer (per D-010, including `CRM_Local.spec` and CI implications).
**Not in scope:** frontend implementation details, visual design (Phase 6 / `docs/DESIGN_RESEARCH.md`), schema DDL (owned by `docs/STAGED_CONTACT_ARCHITECTURE.md`).

---

## 1. Conventions

These apply to **every** endpoint below unless a spec says otherwise. They are stated once here so no per-endpoint spec repeats them.

### 1.1 Base URL, auth, transport

- Base URL: `http://127.0.0.1:{port}` — port selected at startup from 8000–8010 (`app.py:289-298`, `app.py:301-311`). All paths in this document are relative to it.
- **No authentication, by design.** Loopback-only bind, single local user, no tokens, no sessions. (Reference `main.py:142-150` mounts every router with `dependencies=[Depends(verify_token)]` — that Supabase JWT layer is **not** ported; see §6.2.)
- CORS: none configured — correct as-is (cross-origin reads are already browser-blocked; only the write side needs the Origin gate below).
- `openapi_url=None` stays (`app.py:30`) — this document is the contract, not `/docs`.

### 1.2 SEC-03 — Origin/Host gate (stated once, applies to all mutating endpoints)

One middleware (extend the existing security-headers middleware at `app.py:32-38`) enforces on **every** `POST`/`PUT`/`PATCH`/`DELETE`:

- `Origin` header present and not `http://127.0.0.1:{port}` / `http://localhost:{port}` → **403** `ORIGIN_REJECTED`.
- `Host` not in `{127.0.0.1, localhost}[:port]` → **400** `HOST_REJECTED`.
- JSON endpoints additionally require `Content-Type: application/json` → **415** `UNSUPPORTED_MEDIA_TYPE` (multipart intake excepted — §4.1).

Read endpoints (`GET`) are exempt. No per-endpoint SEC-03 note appears anywhere else in this document. (Source: `docs/SECURITY_REVIEW.md` SEC-03, D-028b.)

### 1.3 Error envelope

All non-2xx JSON responses share one shape:

```json
{ "code": "STABLE_CODE", "message": "human-readable, no filesystem paths", "detail": null }
```

- `code` is stable and machine-matchable (SEC-12: never raw `str(exc)` with local paths — log details server-side, return the code).
- Validation failures (FastAPI/pydantic) are normalized to **422** `VALIDATION_ERROR` with `detail` = the pydantic error list.
- Common codes: `VALIDATION_ERROR` (422), `NOT_FOUND` (404), `CONFLICT` (409), `ORIGIN_REJECTED` (403), `HOST_REJECTED` (400), `UNSUPPORTED_MEDIA_TYPE` (415), `PAYLOAD_TOO_LARGE` (413), `IDEMPOTENCY_MISMATCH` (409), `WRITE_PATH_FORBIDDEN` (409, §5.1), `EXTERNAL_TRANSMISSION_NOT_ACKNOWLEDGED` (403), `MODE_LOCAL_ONLY` (409), `MAPPING_NOT_DETECTED` (422).

### 1.4 Async job model — create → poll → done/failed + cancel

Long-running work (intake, folder scan, reprocess, large exports) follows one model:

1. **Create:** `POST` returns **202** with `{"job_id": "...", "state": "queued"}`.
2. **Poll:** `GET /api/jobs/{job_id}` → `{"job_id","state","progress":{"done":n,"total":m},"error":null|{code,message},"results":[...]}`.
   States: `queued → running → done | failed | cancelled`. Terminal states never change again.
3. **Cancel:** `POST /api/jobs/{job_id}/cancel` → 200 with the job in `cancelling` (best-effort) or already-terminal state; a second cancel of a terminal job is a no-op 200 (idempotent).
4. `GET /api/jobs` lists the in-memory job registry (most recent first, capped — §7 Q3).

The current stubs at `app.py:148-151` (always `done`) and `app.py:154-157` (always `cancelled`) are replaced by this real model — QA **P1-8** requires it.

### 1.5 Pagination — keyset, not OFFSET (mandatory)

Per `docs/STAGED_CONTACT_ARCHITECTURE.md` §7.1: `LIMIT ? OFFSET ?` (`db.py:481-492`) rescans skipped rows and drifts when rows are inserted during paging. **Every** list endpoint in this document uses keyset pagination.

**Request params (identical on every list endpoint):**

| Param | Type | Default | Meaning |
|---|---|---|---|
| `size` | int | `50` | page size, max `200` (422 above) |
| `cursor` | string(int) | absent | opaque `id` of the last item of the previous page; **omit on first page** |
| `sort` | string | `id.desc` | `field.asc\|field.desc`, field must be in the endpoint's sort whitelist (422 `VALIDATION_ERROR` otherwise) |
| `q` | string | `""` | free-text search; server treats it as stateless (client debounces input ≥300 ms before requesting) |

**SQL shape (authoritative, from STAGED §7.1):**

```sql
-- unfiltered, newest-first
SELECT ... FROM contacts WHERE id < :cursor ORDER BY id DESC LIMIT :size;
-- filtered queue (review view)
SELECT ... FROM staged_contacts WHERE review_status = :rs AND id < :cursor
ORDER BY id DESC LIMIT :size;
-- total from a separate query: SELECT count(*) ... (same WHERE, no cursor)
```

**Response shape (all list endpoints):**

```json
{
  "items": [ { "...": "row objects, explicit column lists — never SELECT *" } ],
  "next_cursor": "1234",
  "total": 5012
}
```

- `next_cursor` is `null` on the last page. `total` comes from the separate `count(*)`.
- Example two-page walk: `GET /api/contacts?size=3&sort=name.asc` → items with ids `[901, 877, 840]`, `next_cursor: "840"` → `GET /api/contacts?size=3&cursor=840&sort=name.asc` → `WHERE id < 840`.
- Sorts on non-unique fields must be broken by `id` in the ORDER BY (`name ASC, id DESC`) so the cursor stays total-ordering — serverside invariant, not client-visible.

### 1.6 Filter encoding

Structured filters are **repeated single-param triplets**, not nested JSON, so they are curl- and link-friendly:

```
GET /api/contacts?filter=company:eq:Acme&filter=created_at:gte:2026-01-01&filter=email:in:a@x.com,b@y.com
```

- Syntax: `filter={field}:{op}:{value}`; `op ∈ {eq, ne, gt, gte, lt, lte, contains, in}` (`in` = comma-separated).
- Repeat the param for AND semantics. Fields outside the endpoint's filter whitelist → 422.
- `q` (free text) ANDs with `filter`s. `filter` and `tab` (review queue) may combine.
- Multi-value OR beyond `in` is not supported in v1 — clients issue separate queries (deliberate simplification).

### 1.7 Enums (wire values are exact)

| Dimension | Values | Source |
|---|---|---|
| Review status | `NEW`, `NEEDS_REVIEW`, `READY`, `APPROVED`, `REJECTED`, `DISMISSED` | `PRODUCT.md:36` |
| Dedup status | `NOT_CHECKED`, `UNIQUE`, `EXACT_DUPLICATE`, `PROBABLE_DUPLICATE`, `CONFLICT` | `PRODUCT.md:36` |
| Import status | `NOT_IMPORTED`, `NEW_CONTACT_CREATED`, `EXISTING_CONTACT_ENRICHED`, `IMPORT_FAILED` | `PRODUCT.md:36` |
| Import policy | `review_first`, `smart_import`, `always_stage` | spec §4.1 (`ADVANCED_EXTRACTION_SPEC.md:221`); default `review_first` (D-008) |
| Extraction mode | `local_only`, `ai_enrichment` | spec §4.1 (`ADVANCED_EXTRACTION_SPEC.md:220`) |
| Job state | `queued`, `running`, `done`, `failed`, `cancelled`, `cancelling` | §1.4 |
| Validation category | `INVALID`, `SUSPICIOUS`, `MISSING`, `UNCERTAIN`, `FIELD_MAPPING_ERROR`, `POSSIBLE_DUPLICATE`, `CONFLICT` | spec §5.2 (`ADVANCED_EXTRACTION_SPEC.md:273`) |
| Review-queue tab | `all`, `needs_review`, `ready`, `dupes`, `conflicts`, `imported`, `rejected`, `failed` | parity §3.1 row 9 (`CRM_FEATURE_PARITY.md:222`) |
| Provider allow-list | `openrouter`, `groq`, `gemini`, `openai`, `deepseek`, `anthropic`, `ollama` | spec §4, brief (7 providers) |
| Export format | `xlsx`, `csv`, `pdf`, `vcf`, `zip` | D-013 |

Unknown enum value → 422 `VALIDATION_ERROR`.

### 1.8 Content types

- Requests: `application/json; charset=utf-8` (except `POST /api/intake` = `multipart/form-data`, and folder paths endpoints which are JSON).
- Responses: JSON UTF-8; file downloads set `Content-Disposition: attachment; filename="…"` and the matching MIME (XLSX `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, CSV `text/csv`, PDF `application/pdf`, VCF `text/vcf`, ZIP `application/zip`).
- **No endpoint ever returns HTML or executes server-rendered content.**

### 1.9 Idempotency

Endpoints with side effects that a client may retry carry an optional `Idempotency-Key` header (UUID):

- **Approve family:** `POST /api/staged/{id}/approve`, `/approve-selected`, `/approve-all-safe`. Replaying the same key returns the original response (200), never re-runs approval. Approve is *naturally* idempotent too (approving an already-`APPROVED` row returns 200 with `already_approved: true` — QA P0-2 `test_duplicate_approve_is_idempotent`); the key guards network-level retries of *bulk* calls where partial progress occurred.
- **Export:** `POST /api/export` with the same key returns the identical generated artifact (no double generation for a heavy PDF/ZIP).
- Same key + different body → 409 `IDEMPOTENCY_MISMATCH`. Keys are held in memory for 24 h.
- Everything else (reject/dismiss/restore are state transitions; PATCH is last-write-wins) needs no key.

### 1.10 Canonical-write rule (D-007) — applies to import flows

**Staged → canonical writes happen only through approval endpoints (or the programmatic Smart-Import gate).** No intake, scan, job, or reprocess endpoint may write `contacts`/`companies` directly. Enforced by QA P0-3 (static grep gate: `intake.py`/`pipeline.py` contain no direct `upsert_contact`/`insert_eml_contact` calls). Manual user CRUD (Phase 3) is a separate, user-initiated write — see §7 Q1.

---

## 2. Router module map (D-010)

D-010: routes move into an `api/` package (reference pattern); the same change updates `CRM_Local.spec` hiddenimports and CI test paths; owner = backend engineer.

### 2.1 Target layout

`app.py` stays as **composition root only** and keeps exactly what is listed in the "stays" column; everything else moves:

| Router file | Owns (endpoints) | Migrated from |
|---|---|---|
| `api/__init__.py` | exports routers | — (new) |
| `api/system.py` | `GET /api/health`, `GET /api/status`, `POST /api/autostart` | `app.py:90-103`, `app.py:263-283` |
| `api/settings.py` | `GET/POST /api/settings`, `GET/PUT /api/settings/mode`, all `/api/providers*` | `app.py:160-172`, `app.py:253-256` |
| `api/intake.py` | `POST /api/intake`, `POST /api/scan`, `POST /api/pick-folder`, `POST /api/open-folder`, `POST /api/mapping/detect` | `app.py:136-145`, `app.py:128-133`, `app.py:231-250` |
| `api/jobs.py` | `GET /api/jobs`, `GET /api/jobs/{job_id}`, `POST /api/jobs/{job_id}/cancel` | `app.py:148-157` |
| `api/staging.py` | all `/api/staged*` (Review Queue) | net-new |
| `api/history.py` | `GET /api/history`, `POST /api/history/{file_id}/reprocess` | net-new (P-12) |
| `api/contacts.py` | `/api/contacts*` incl. sub-resources, bulk, undo | `app.py:175-211` |
| `api/companies.py` | `/api/companies*` incl. merge | net-new (P-8) |
| `api/emails.py` | `GET /api/emails`, `GET /api/emails/{id}` | net-new (P-10) |
| `api/calls.py` | `/api/calls*`, `/api/follow-ups*` | net-new (P-11) |
| `api/notes.py` | `/api/notes*`, `/api/tags*`, `/api/views*` | net-new (P-18) |
| `api/duplicates.py` | `/api/duplicates*` incl. merge | net-new (P-6 read side) |
| `api/quality.py` | `GET /api/quality`, `GET /api/quality/{category}` | net-new (P-5) |
| `api/search.py` | `GET /api/search` (global + command palette) | net-new (P-9) |
| `api/reports.py` | `POST /api/export` | `app.py:214-228` |
| `api/dashboard.py` | `GET /api/dashboard` | net-new (P-15) |
| `api/mapping.py` | `GET/POST /api/templates`, `PUT/DELETE /api/templates/{id}` | net-new (D-023) |

**Stays in `app.py`:** FastAPI app construction + `openapi_url=None` (`app.py:30`), the security-headers **and** SEC-03 middleware (`app.py:32-38`, extended per §1.2), startup hook (`app.py:78-82`), `GET /` index (`app.py:85-87`), static mount (`app.py:286`), PyInstaller windowed-exe guard (`app.py:7-11`), `_free_port`/`main()` (`app.py:289-311`), and `app.include_router(..., prefix="/api")` for every router above — mirroring reference `main.py:142-150`, **minus** `verify_token`.

### 2.2 `CRM_Local.spec` implications (backend engineer owns)

- `hiddenimports` (`CRM_Local.spec:8-14`) gains every `api.*` module if PyInstaller's static analysis misses them (it should not — they are directly imported by `app.py` — but D-010 makes this the same change's responsibility), plus new runtime deps: `python-multipart` (D-009), `reportlab` (D-013).
- `datas=[("static","static")]` (`CRM_Local.spec:7`) already bundles nested static dirs — no change.

### 2.3 CI implications (backend engineer owns)

- `tests/test_app.py:4` does `from app import app` — that import must keep working unchanged (app.py remains the composition root; routers are pulled in transitively). CI command `python -m pytest tests/ -q` needs no path change; **new** test files (`test_staging.py`, `test_jobs.py`, `test_security_*.py`, …) are picked up by the existing glob.
- The policy/static grep jobs (QA §"Policy/static") gain two greps owned by this split: (a) no route function bodies left in `app.py` (only middleware/mount/entry); (b) canonical-write-path single-ness (P0-3).

---

## 3. Endpoint catalogue

**★ = Phase-2-critical** (the staging round-trip; QA P0-2/P0-3/P1-8 guard it). "Exists" cites the current route with `file:line`.

| # | Method | Path | Purpose | Phase | Router file | Notes |
|---|---|---|---|---|---|---|
| 1 | GET | `/api/health` | liveness probe (`{"ok":true}`) | 2 | `api/system.py` | net-new (reference has `/health`; target has none today) |
| 2 | GET | `/api/status` | counts, pending, run snapshot, providers, `external_requests_in_progress`, version | 2 | `api/system.py` | exists `app.py:90-103`; extend per spec §4.4 |
| 3 ★ | GET | `/api/settings` | **masked** config: `api_key_set`, never keys (SEC-01) | 2 | `api/settings.py` | exists `app.py:160-163` — currently leaks keys |
| 4 ★ | POST | `/api/settings` | partial update; `api_key` write-only (empty = keep stored) | 2 | `api/settings.py` | exists `app.py:166-172` |
| 5 | GET | `/api/config` | **RETIRED → 410** `CONFIG_RETIRED` | 2 | — (deleted) | exists `app.py:106-112`; D-011 |
| 6 | POST | `/api/config` | **RETIRED → 410** | 2 | — (deleted) | exists `app.py:115-125`; D-011 |
| 7 ★ | GET | `/api/providers` | masked provider list (`has_key`, `last_test`, `order`) | 2 | `api/settings.py` | net-new; spec §4.2 |
| 8 ★ | POST | `/api/providers` | add provider (write-only `api_key`) | 2 | `api/settings.py` | net-new |
| 9 ★ | PATCH | `/api/providers/{id}` | edit model/base_url/timeout_s/max_retries/key | 2 | `api/settings.py` | net-new |
| 10 | DELETE | `/api/providers/{id}` | remove provider | 2 | `api/settings.py` | net-new |
| 11 | POST | `/api/providers/{id}/enable` | enable | 2 | `api/settings.py` | net-new |
| 12 | POST | `/api/providers/{id}/disable` | disable | 2 | `api/settings.py` | net-new |
| 13 | PUT | `/api/providers/order` | reorder failover chain | 2 | `api/settings.py` | net-new |
| 14 ★ | POST | `/api/providers/{id}/test` | live provider test | 2 | `api/settings.py` | replaces `POST /api/test-llm` exists `app.py:253-256` |
| 15 ★ | GET | `/api/settings/mode` | `mode` + `import_policy` | 2 | `api/settings.py` | net-new; default `review_first` (D-008) |
| 16 ★ | PUT | `/api/settings/mode` | set mode/policy | 2 | `api/settings.py` | net-new |
| 17 ★ | POST | `/api/intake` | **multipart** universal intake (6 formats) → job | 2 | `api/intake.py` | exists `app.py:136-145` — transport changes (D-009), path-list form deleted (SEC-05) |
| 18 | GET | `/api/jobs` | list jobs | 2 | `api/jobs.py` | net-new |
| 19 ★ | GET | `/api/jobs/{job_id}` | poll job | 2 | `api/jobs.py` | exists `app.py:148-151` — **stub** → real (P1-8) |
| 20 ★ | POST | `/api/jobs/{job_id}/cancel` | cancel job | 2 | `api/jobs.py` | exists `app.py:154-157` — **stub** → real |
| 21 ★ | GET | `/api/staged` | Review Queue list: `tab` + filters + keyset | 2 | `api/staging.py` | net-new — **the** Phase-2 read surface |
| 22 ★ | GET | `/api/staged/{id}` | staged detail: fields, raw source, validation issues, provenance | 2 | `api/staging.py` | net-new |
| 23 ★ | PATCH | `/api/staged/{id}` | edit-before-approve | 2 | `api/staging.py` | net-new (field allow-list, SEC-04 pattern) |
| 24 ★ | POST | `/api/staged/{id}/approve` | approve → canonical (D-007), local-wins merge (STAGED §6.2) | 2 | `api/staging.py` | net-new |
| 25 ★ | POST | `/api/staged/approve-selected` | bulk approve, partial-failure report, idempotent | 2 | `api/staging.py` | net-new |
| 26 ★ | POST | `/api/staged/approve-all-safe` | approve all `READY`+`UNIQUE` only | 2 | `api/staging.py` | net-new (§7 Q4) |
| 27 ★ | POST | `/api/staged/{id}/reject` | reject (stays staged, canonical untouched) | 2 | `api/staging.py` | net-new |
| 28 ★ | POST | `/api/staged/{id}/dismiss` | dismiss noise row | 2 | `api/staging.py` | net-new |
| 29 ★ | POST | `/api/staged/{id}/restore` | undo reject/dismiss → `NEEDS_REVIEW` | 2 | `api/staging.py` | net-new |
| 30 ★ | POST | `/api/staged/{id}/merge-into-existing` | fold staged row into a canonical contact | 2 | `api/staging.py` | net-new; before-image audit (D-014) |
| 31 ★ | POST | `/api/staged/{id}/conflict-resolve` | resolve `CONFLICT` dedup with user field picks | 2 | `api/staging.py` | net-new |
| 32 ★ | GET | `/api/staged/{id}/duplicates` | candidate matches for one staged row (compare pane) | 2 | `api/staging.py` | net-new |
| 33 | POST | `/api/scan` | folder scan → job | 4 | `api/intake.py` | exists `app.py:128-133`; becomes async-job create |
| 34 | POST | `/api/pick-folder` | native folder dialog | 4 | `api/intake.py` | exists `app.py:231-236` |
| 35 | POST | `/api/open-folder` | open folder in OS file manager | 4 | `api/intake.py` | exists `app.py:239-250` |
| 36 | GET | `/api/history` | processed-file ledger (file, type, counts, duration, errors) | 4 | `api/history.py` | net-new (P-12) |
| 37 | POST | `/api/history/{file_id}/reprocess` | delete ledger row + requeue → job | 4 | `api/history.py` | net-new (§5.3) |
| 38 | POST | `/api/mapping/detect` | server-side 25-type header-mapping detection (D-023) | 4 | `api/mapping.py` | net-new |
| 39 | GET | `/api/templates` | saved import templates | 4 | `api/mapping.py` | net-new |
| 40 | POST | `/api/templates` | create template | 4 | `api/mapping.py` | net-new |
| 41 | PUT | `/api/templates/{id}` | update template | 4 | `api/mapping.py` | net-new |
| 42 | DELETE | `/api/templates/{id}` | delete template | 4 | `api/mapping.py` | net-new |
| 43 ★ | GET | `/api/contacts` | keyset list + `sort`/`filter`/`q` | 3 | `api/contacts.py` | exists `app.py:175-183` — `page`/`size` OFFSET params replaced (§1.5); `which` param dropped (§7 Q2) |
| 44 | POST | `/api/contacts` | manual contact create | 3 | `api/contacts.py` | net-new; user-initiated (§7 Q1) |
| 45 | GET | `/api/contacts/{id}` | contact detail | 3 | `api/contacts.py` | net-new |
| 46 | PATCH | `/api/contacts/{id}` | inline edit — **column allow-list**, 422 unknown keys (SEC-04) | 3 | `api/contacts.py` | exists as `/api/contacts/{which}/{id}` `app.py:186-197` |
| 47 | DELETE | `/api/contacts/{id}` | **soft-delete** (`deleted_at`, D-014) | 3 | `api/contacts.py` | exists `app.py:200-211` — hard delete today (`db.py:509`) |
| 48 | POST | `/api/contacts/{id}/undo` | restore soft-deleted contact | 3 | `api/contacts.py` | net-new |
| 49 | POST | `/api/contacts/bulk` | bulk edit / bulk soft-delete (returns per-id results) | 3 | `api/contacts.py` | net-new |
| 50 | GET | `/api/contacts/{id}/emails` | contact's emails (keyset) | 5 | `api/contacts.py` | net-new |
| 51 | GET | `/api/contacts/{id}/calls` | contact's calls | 3 | `api/contacts.py` | net-new |
| 52 | GET/POST | `/api/contacts/{id}/notes` | contact notes | 3 | `api/notes.py` | net-new |
| 53 | GET | `/api/contacts/{id}/provenance` | field→source-file evidence | 3 | `api/contacts.py` | net-new (STAGED §6.4) |
| 54 | GET/POST | `/api/contacts/{id}/follow-ups` | follow-ups on a contact | 3 | `api/calls.py` | net-new |
| 55 | GET/POST/DELETE | `/api/contacts/{id}/tags` | tag membership | 3 | `api/notes.py` | net-new |
| 56 | GET | `/api/companies` | companies list (keyset) | 3 | `api/companies.py` | net-new (P-8) |
| 57 | POST | `/api/companies` | create company | 3 | `api/companies.py` | net-new |
| 58 | GET | `/api/companies/{id}` | company detail + associated contacts | 3 | `api/companies.py` | net-new |
| 59 | PATCH | `/api/companies/{id}` | edit company | 3 | `api/companies.py` | net-new |
| 60 | DELETE | `/api/companies/{id}` | soft-delete company | 3 | `api/companies.py` | net-new |
| 61 | POST | `/api/companies/{id}/merge` | merge company (before-image audit, D-014) | 3 | `api/companies.py` | net-new |
| 62 | GET | `/api/emails` | two-pane list: thread/date/subject/participants (keyset) | 5 | `api/emails.py` | net-new (P-10) |
| 63 | GET | `/api/emails/{id}` | email detail + body (sanitized) + related contacts | 5 | `api/emails.py` | net-new |
| 64 | GET | `/api/calls` | calls list (keyset, filters by date/type/outcome) | 3 | `api/calls.py` | net-new; port reference `api/calls.py:61,92,111,135` shape |
| 65 | POST | `/api/calls` | log a call | 3 | `api/calls.py` | net-new |
| 66 | PATCH | `/api/calls/{id}` | edit call | 3 | `api/calls.py` | net-new |
| 67 | DELETE | `/api/calls/{id}` | delete call | 3 | `api/calls.py` | net-new |
| 68 | GET | `/api/follow-ups` | all follow-ups, `status=open\|done`, due-date sort | 3 | `api/calls.py` | net-new |
| 69 | PATCH | `/api/follow-ups/{id}` | complete/edit follow-up | 3 | `api/calls.py` | net-new |
| 70 | GET/POST | `/api/notes` | global notes CRUD list/create | 3 | `api/notes.py` | net-new |
| 71 | PATCH/DELETE | `/api/notes/{id}` | edit/delete note | 3 | `api/notes.py` | net-new |
| 72 | GET/POST | `/api/tags` | tag list/create | 3 | `api/notes.py` | net-new |
| 73 | DELETE | `/api/tags/{id}` | delete tag (membership rows cascade) | 3 | `api/notes.py` | net-new |
| 74 | GET/POST | `/api/views` | saved views (name, entity, sort/filter snapshot) | 3 | `api/notes.py` | net-new |
| 75 | PUT/DELETE | `/api/views/{id}` | update/delete saved view | 3 | `api/notes.py` | net-new |
| 76 | GET | `/api/duplicates` | duplicate pairs (keyset; `tier=exact\|probable\|conflict`) | 5 | `api/duplicates.py` | net-new (P-6) |
| 77 | GET | `/api/duplicates/{pair_id}` | field-level side-by-side compare | 5 | `api/duplicates.py` | net-new |
| 78 | POST | `/api/duplicates/{pair_id}/merge` | field-level merge submit + **before-image audit** (D-014) | 5 | `api/duplicates.py` | net-new (§5.2) |
| 79 | GET | `/api/quality` | 7-category issue counts | 5 | `api/quality.py` | net-new (P-5) |
| 80 | GET | `/api/quality/{category}` | issues in one category (keyset, `filter` by field) | 5 | `api/quality.py` | net-new |
| 81 | POST | `/api/export` | formula-safe XLSX/CSV/PDF/VCF/ZIP, filtered/selected, idempotent | 6 | `api/reports.py` | replaces `GET /api/export` exists `app.py:214-228` (XLSX-only, unfiltered) |
| 82 | GET | `/api/dashboard` | KPIs + recent activity + actionable items — **real DB values only** | 6 | `api/dashboard.py` | net-new (P-15); absorbs D-012 textual summaries |
| 83 | GET | `/api/search` | global search across contacts/companies/emails/phones/addresses/files/activities; `scope=palette` variant | 6 | `api/search.py` | net-new (P-9); FTS5 index ships Phase 5 (D-020/D-030) |
| 84 | POST | `/api/autostart` | Windows autostart toggle | 6 | `api/system.py` | exists `app.py:263-283` — unchanged semantics |
| 85 | GET | `/` | index.html | — | `app.py` (stays) | exists `app.py:85-87` |
| 86 | — | `/static/*` | StaticFiles mount | — | `app.py` (stays) | exists `app.py:286` |

**Total: 86 catalogue entries (84 API endpoints + 2 static/root rows), of which 24 are ★ Phase-2-critical.**

---

## 4. Endpoint specifications

Selected ~22 specs: every ★-cluster representative plus one per Phase 3–6 capability family. Conventions (§1) are not repeated.

### 4.1 `POST /api/intake` ★ (Phase 2) — universal multipart intake

Replaces the path-list body at `app.py:136-145` (D-009; also closes SEC-05 path-containment hole — server receives **bytes**, never filesystem paths).

- **Request:** `multipart/form-data`; repeated `files` parts (XLSX, XLS, CSV, PDF, TXT, EML); optional `policy` field overriding the default `review_first` (D-008); max 50 files, 10 MB/file, 100 MB/batch → **413** `PAYLOAD_TOO_LARGE`.
- **Response:** `202`

```json
{
  "job_id": "j-7f3a",
  "state": "queued",
  "files": [
    {"filename": "leads_q4.xlsx", "bytes": 48211},
    {"filename": "signature.eml", "bytes": 9120}
  ]
}
```

- **Errors:** 415 unsupported extension (per-file entry in `results`, not a whole-batch failure), 413 over cap, 422 no files, 403 `MODE_LOCAL_ONLY` never applies here (intake is local), `EXTERNAL_TRANSMISSION_NOT_ACKNOWLEDGED` when `mode=ai_enrichment` unacknowledged and Layer-2 would fire (spec §4.4).
- **Side effects:** writes `staged_contacts` rows (never `contacts` — §1.10), `processed_files` ledger row per file, validation issues per record (§5.2 categories); opens one job. Job result payload (§1.4 `results`): per-file `{filename, state, staged: n, warnings: [...], errors: [...]}`.
- **Poll:** §4.2.

### 4.2 `GET /api/jobs/{job_id}` ★ (Phase 2)

- **Response:** `200`

```json
{
  "job_id": "j-7f3a",
  "state": "running",
  "progress": {"done": 3, "total": 5},
  "error": null,
  "results": [
    {"filename": "leads_q4.xlsx", "state": "done", "staged": 41, "warnings": ["MISSING:row 12 no email/phone"], "errors": []}
  ]
}
```

- Terminal: `state ∈ {done, failed, cancelled}`, `error` = `{code, message}` on `failed` (e.g. `EXTRACTION_CONTRACT_VIOLATION`). Unknown id → 404 `NOT_FOUND`. Replaces stub `app.py:148-151`.

### 4.3 `POST /api/jobs/{job_id}/cancel` ★ (Phase 2)

- **Response:** `200` `{"job_id":"j-7f3a","state":"cancelling"}`; if already terminal → `200` with current terminal state (idempotent). Unknown id → 404. Best-effort: files already staged stay staged (they're reviewable/dismissable). Replaces stub `app.py:154-157`.

### 4.4 `GET /api/staged` ★ (Phase 2) — Review Queue list

- **Params:** §1.5 keyset + `tab` (§1.7) + direct filters `review_status`, `dedup_status`, `import_status` (as `filter` triplets or dedicated params — dedicated params win on conflict) + `q`.
- **Sort whitelist:** `id`, `created_at`, `name`, `company`, `review_status`, `dedup_status`.
- **Response:** `200`

```json
{
  "items": [
    {
      "id": 412,
      "review_status": "NEEDS_REVIEW",
      "dedup_status": "PROBABLE_DUPLICATE",
      "import_status": "NOT_IMPORTED",
      "name": "Ravi Kumar",
      "company": "Acme Pipes",
      "email": "ravi@acmepipes.in",
      "phone": "+919876543210",
      "source_type": "xlsx",
      "source_file": "leads_q4.xlsx",
      "duplicate_of_contact_id": 88,
      "validation_issues_count": 2,
      "created_at": "2026-11-07T10:12:44Z"
    }
  ],
  "next_cursor": "412",
  "total": 137
}
```

- **Errors:** 422 unknown `tab`/sort/filter field. Never returns `body_text`/`raw_source_data` (detail endpoint does).

### 4.5 `GET /api/staged/{id}` ★ (Phase 2)

- **Response:** `200` — the row above plus `fields` (full normalized record incl. all preserved `phone_secondary` values, D-027), `raw_source_data`, `validation_issues` (`[{record_ref, field, category, detail, raw_value}]`, §5.2 categories), `provenance` (`{source_file, source_row, extraction_run_id, layer1, layer2}`), `conflicts` (what local-wins refused to change, STAGED §6.3), `duplicates` summary `{exact: 0, probable: 1}`.
- **Errors:** 404.

### 4.6 `POST /api/staged/{id}/approve` ★ (Phase 2) — the only canonical write gate

- **Request:** optional `{"fields": {...}}` last-moment overrides (same allow-list as PATCH); optional `Idempotency-Key` (§1.9).
- **Response:** `200`

```json
{
  "staged_id": 412,
  "contact_id": 91,
  "import_status": "NEW_CONTACT_CREATED",
  "already_approved": false,
  "company_id": 12,
  "local_wins": ["phone_secondary preserved from local row"],
  "conflicts": []
}
```

- **Side effects (one transaction, STAGED §6.1):** insert/update canonical `contacts` (+ find-or-create `companies` **at approval time only**, D-007); dedup keys upserted; staged row → `APPROVED`/`NEW_CONTACT_CREATED`; provenance columns written (STAGED §6.4); before-image captured if it merged into an existing contact (D-014).
- **Errors:** 404 unknown staged id; 409 `CONFLICT` if `dedup_status=CONFLICT` and no `conflicts` resolution supplied (route to §4.11 instead); 409 if row already `REJECTED` (must restore first); idempotent replay → 200 `already_approved: true`.

### 4.7 `POST /api/staged/approve-selected` ★ (Phase 2)

- **Request:** `{"staged_ids": [412, 415, 419], "skip_conflicts": true}` + `Idempotency-Key`.
- **Response:** `200` — **partial-failure reporting** (reference `push-bulk` shape, `api/eml.py:500`):

```json
{
  "approved": [{"staged_id": 412, "contact_id": 91}],
  "skipped": [{"staged_id": 415, "reason": "CONFLICT"}, {"staged_id": 419, "reason": "ALREADY_APPROVED"}],
  "failed": []
}
```

- **Errors:** 422 empty `staged_ids`; 409 `IDEMPOTENCY_MISMATCH` (same key, different ids).

### 4.8 `POST /api/staged/approve-all-safe` ★ (Phase 2)

- **Semantics:** approves every row with `review_status=READY` **and** `dedup_status=UNIQUE` (§7 Q4). Never touches `CONFLICT`/`PROBABLE_DUPLICATE` rows — that is the "safe" guarantee.
- **Response:** `200` `{"considered": 84, "approved": 81, "skipped": [{"staged_id": 402, "reason": "NOT_READY"}], "failed": []}`.
- Idempotent (second call finds zero safe rows → `approved: 0`).

### 4.9 `POST /api/staged/{id}/reject` · `/dismiss` · `/restore` ★ (Phase 2)

Three state transitions with one shape (spec'd together — identical contract, different target state):

- **reject:** → `REJECTED`. **Canonical untouched** (QA P0-2 `test_reject_leaves_canonical_untouched`). Response `200 {"staged_id":412,"review_status":"REJECTED"}`.
- **dismiss:** → `DISMISSED` (noise, not a contact candidate). Same response shape.
- **restore:** → `NEEDS_REVIEW` from `REJECTED`/`DISMISSED`. Same shape; from any other state → 409 `CONFLICT`.
- All idempotent (repeating on a row already in the target state → 200, no-op). 404 unknown id.

### 4.10 `POST /api/staged/{id}/merge-into-existing` ★ (Phase 2)

- **Request:** `{"target_contact_id": 88, "field_picks": {"phone": "staged", "email": "canonical", "company": "canonical"}}`
- **Response:** `200` `{"staged_id":412, "contact_id":88, "audit_id": "ma-17", "import_status":"EXISTING_CONTACT_ENRICHED"}`
- **Side effects:** target contact updated with picked values (local-wins: picks apply only where allowed, STAGED §6.2); **before-image audit row written first** — `{table, row_id, field, old_value, new_value, actor:"merge", at}` (D-014, enables merge undo) — staged row → `APPROVED`/`EXISTING_CONTACT_ENRICHED`.
- **Errors:** 404 either id; 409 if `target_contact_id` == the staged row's own canonical shadow; 422 unknown field in `field_picks`.

### 4.11 `POST /api/staged/{id}/conflict-resolve` ★ (Phase 2)

- **Request:** `{"resolutions": {"email": "staged", "name": "canonical"}}` — per-field `staged|canonical|value:<literal>`.
- **Response:** `200 {"staged_id":412,"dedup_status":"UNIQUE","review_status":"READY"}` — resolution unblocks approve.
- **Errors:** 409 if `dedup_status != CONFLICT`; 422 unknown field.

### 4.12 `GET /api/settings` ★ / `POST /api/settings` ★ (Phase 2) — SEC-01

- **GET response (masked — replaces the leak at `app.py:160-163`):**

```json
{
  "crm_dir": "C:\\CRM\\data",
  "eml_dir": "C:\\CRM\\mail",
  "theme": "light",
  "watch": true,
  "watch_interval": 30,
  "autostart": false,
  "mode": "local_only",
  "import_policy": "review_first",
  "config_path": "C:\\Users\\me\\AppData\\...\\config.json",
  "crm_db_path": "...", "eml_db_path": "..."
}
```

`chain` is **absent** — provider keys live only behind `/api/providers` (§4.13). Never any `api_key`/`api_key_set` on this endpoint (SEC-01: four endpoints covered — `app.py:106-112,125,160-172` per D-028a; two are retired, two are these).

- **POST:** partial update (`exclude_none`, as `app.py:166-172` does today); accepts only the non-secret keys above + `mode`/`import_policy` (enum-checked). Response = the new masked GET body. 422 unknown key (allow-list — closes mass-assignment).
- Side effects: `watch` change starts/stops the watcher (current behaviour `app.py:121-124`); config file written `0600` (D-028).

### 4.13 `POST /api/providers/{id}/test` ★ (Phase 2) — replaces `POST /api/test-llm`

- **Response:** `200 {"ok": true, "provider": "groq", "model": "llama-3.3-70b-versatile", "latency_ms": 412, "detail": "ok"}` — failure is a **200 with `ok:false`** (a failed test is a result, not an HTTP error): `{"ok": false, "detail": "AUTH_FAILED"}`. Provider-not-found → 404. `mode=local_only` → 409 `MODE_LOCAL_ONLY` (no external calls, spec §4.4). Never echoes the key; `last_test` persisted masked.

### 4.14 `GET /api/contacts` (Phase 3) — keyset in anger

- **Params:** §1.5 exactly. Sort whitelist: `id`, `name`, `company`, `email`, `created_at`. Filter whitelist: `company`, `email`, `phone`, `city`, `industry`, `position`, `deleted_at`, `created_at`, `tag`.
- **Example:** `GET /api/contacts?size=2&sort=name.asc&filter=company:eq:Acme Pipes&q=ravi`

```json
{
  "items": [
    {"id": 91, "name": "Ravi Kumar", "company": "Acme Pipes", "email": "ravi@acmepipes.in",
     "phone": "+919876543210", "position": "Purchase Head", "deleted_at": null, "tag": ["vip"]}
  ],
  "next_cursor": "91",
  "total": 1
}
```

- Soft-deleted rows excluded unless `filter=deleted_at:isnotnull` (undo screen). Replaces `{rows,total,page,size}` at `app.py:175-183` — **breaking change**, frontend updated in the same PR (§6.1 row 12).
- **Errors:** 422 bad sort/filter/`size>200`.

### 4.15 `PATCH /api/contacts/{id}` (Phase 3)

- **Request:** `{"fields": {"position": "Head of Purchase", "city": "Pune"}}` — keys validated against the `contacts` column allow-list → unknown key **422** `VALIDATION_ERROR` (SEC-04: today `app.py:186-197` passes `ContactIn.fields: dict` straight through; `db.update_contact` builds `f"{k}=?"` from request keys).
- **Response:** `200 {"ok": true, "updated": ["position","city"]}`; 404 unknown id; 409 on soft-deleted row (restore first).
- Side effect: `updated_at` bump; no provenance overwrite (user edits are their own provenance layer).

### 4.16 `DELETE /api/contacts/{id}` + `POST /api/contacts/{id}/undo` (Phase 3) — D-014

- **DELETE:** soft — sets `deleted_at`. `200 {"ok":true,"deleted_at":"2026-11-07T11:00:00Z"}`. Idempotent: second delete → 200 with existing timestamp. Replaces hard delete (`db.py:509` via `app.py:200-211`).
- **undo:** `200 {"ok":true,"deleted_at":null}`; 409 if not deleted.

### 4.17 `GET /api/contacts/{id}/provenance` (Phase 3)

- **Response:** `200 {"contact_id": 91, "fields": [{"field":"email","source_file":"leads_q4.xlsx","source_row":12,"layer":"layer1","at":"..."}], "staged_id": 412, "import_session": null}` — STAGED §6.4 columns surfaced read-only. 404 unknown id.

### 4.18 `POST /api/scan` (Phase 4) — folder scan becomes a job

- **Request:** `{"which": "all"}` (valid `crm|eml|all`, as `app.py:128-133`) → `202 {"job_id":"j-91c2","state":"queued","started":"all"}`. Same job model as intake (§1.4); scan writes staged rows only (§1.10) — the auto-push at `pipeline.py:164-171` is deleted in Phase 2.

### 4.19 `GET /api/history` + `POST /api/history/{file_id}/reprocess` (Phase 4)

- **GET:** keyset list over `processed_files`: `{"items":[{"file_id":12,"path_hash":"…","filename":"leads_q4.xlsx","format":"xlsx","status":"done","contacts_found":41,"duration_ms":3820,"error":null,"processed_at":"..."}],"next_cursor":"12","total":308}`. `path_hash`, not raw absolute path (SEC-12); `filename` is basename only.
- **reprocess:** `202 {"job_id":"j-a01","file_id":12}` — deletes the ledger row, requeues the file through the *current* pipeline → re-stages (never re-writes canonical; §1.10). 404 unknown file; 409 if a job for it is already running.

### 4.20 `GET /api/emails` + `GET /api/emails/{id}` (Phase 5) — two-pane

- **GET list:** keyset; filters `from`, `to`, `date_from`, `date_to`, `has_attachments`; sort `date.desc` default. Items: `{id, thread_id, date, from, to, subject, snippet, contact_ids, has_attachments}` — snippet is plain text, ≤200 chars.
- **GET detail:** adds `body_html` **sanitized server-side** (SEC-02 precondition for the Emails view — raw `innerHTML` never renders it) and `related_contacts: [{id, name, match: "email_key"}]`. 404.

### 4.21 `GET /api/duplicates` + `POST /api/duplicates/{pair_id}/merge` (Phase 5)

- **GET list:** keyset; `filter=tier:eq:probable`; items `{pair_id, tier, left:{id,name,company,email}, right:{...}, match_reason:"email_key", confidence:0.92}`.
- **GET `{pair_id}`:** field-level compare: `{fields: [{field, left_value, right_value, same: false, source_left, source_right}]}`.
- **merge:** `{"field_picks": {"email": "left", "phone": "right", "company": "left"}}` → `200 {"survivor_id":88,"merged_id":91,"audit_id":"ma-18"}`. **Side effects:** survivor keeps everything (STAGED §6.6 checklist); loser soft-deleted with `merged_into_id` set; **before-image audit row per changed field written first** (D-014); 422 unknown pick field; 409 same id twice.

### 4.22 `GET /api/quality` (Phase 5)

- **Response:** `200` — the 7 categories (§1.7) with counts + top offenders:

```json
{"categories": [
  {"category": "MISSING", "count": 41, "fields": {"email": 22, "phone": 19}},
  {"category": "POSSIBLE_DUPLICATE", "count": 12},
  {"category": "INVALID", "count": 5}, "...": "..."
], "total_issues": 96}
```

- `GET /api/quality/{category}` → keyset issue rows `{record_ref, field, category, detail, raw_value}` (spec §5.2 linkage). Unknown category → 404.

### 4.23 `POST /api/export` (Phase 6) — formula-safe, filtered, idempotent

- **Request:**

```json
{
  "format": "xlsx",
  "entity": "contacts",
  "filters": [{"field": "company", "op": "eq", "value": "Acme Pipes"}],
  "selection_ids": null,
  "q": ""
}
```

- **Response:** binary stream + `Content-Disposition` (§1.8). Row cap 100,000 → 413 beyond. **Formula injection:** every cell whose text starts with `= + - @ \t \r` is prefixed `'` (port reference `api/eml.py:416-421`; today only XLSX is sanitized `export.py:37-40` — CSV/PDF/VCF/ZIP get the same treatment). `Idempotency-Key` supported (§1.9). `format=vcf` uses stdlib vCard writer, `zip` uses `zipfile` (D-013 — no JSZip/CDN), `pdf` uses `reportlab` (new dep + spec hiddenimports).
- Replaces unfiltered XLSX-only `GET /api/export` (`app.py:214-228`). 422 unknown format/entity, 413 over cap.

### 4.24 `GET /api/dashboard` (Phase 6)

- **Response:** `200` — every number from SQL (P-15; today `static/app.js:56-61` fabricates KPIs):

```json
{
  "kpis": {"contacts": 5123, "companies": 318, "emails": 12044, "staged_needs_review": 37,
           "open_followups": 9, "quality_issues": 96},
  "recent_activity": [{"at": "...", "text": "Imported 41 contacts from leads_q4.xlsx"}],
  "actionable": [{"kind": "staged_needs_review", "count": 37, "href": "/#/review?tab=needs_review"},
                 {"kind": "possible_duplicates", "count": 12, "href": "/#/duplicates"}]
}
```

- No charts/graphs anywhere (PRODUCT.md hard constraint). D-012's textual summaries live in `recent_activity`.

### 4.25 `GET /api/search` (Phase 6)

- **Params:** `q` (≥2 chars), `scope=all|contacts|companies|emails|activities|files`, `limit` (default 20). Command palette calls `scope=all` with `limit=8`.
- **Response:** `200 {"results": [{"type":"contact","id":91,"title":"Ravi Kumar — Acme Pipes","subtitle":"ravi@acmepipes.in","score":0.98}], "total": 4}` — searches names, companies, emails, phones, addresses, source files, activities (P-9). FTS5-backed from Phase 5 (D-020: tokenizer decided then, runtime capability check; trigram preferred for phone-substring).

---

## 5. Workflow sequences

### 5.1 Intake → job → staged → approve (the Phase-2 round-trip; QA P0-2)

```mermaid
sequenceDiagram
  participant UI as Browser
  participant API as api/intake.py
  participant JOB as api/jobs.py
  participant STG as api/staging.py
  participant DB as crm.db

  UI->>API: POST /api/intake (multipart, 2 files)
  API->>DB: insert staged_contacts (review=NEW/NEEDS_REVIEW, import=NOT_IMPORTED)
  API->>DB: insert processed_files ledger row (per file)
  API-->>UI: 202 {job_id}
  loop every 500ms
    UI->>JOB: GET /api/jobs/{id}
    JOB-->>UI: {state: running, progress: {done:1,total:2}}
  end
  UI->>STG: GET /api/staged?tab=needs_review
  STG-->>UI: {items:[...], next_cursor, total}
  UI->>STG: GET /api/staged/412 (detail: raw + issues + duplicates)
  UI->>STG: POST /api/staged/412/approve {Idempotency-Key: k1}
  STG->>DB: BEGIN; before-image? → upsert contacts + companies (D-007 local-wins fill, STAGED §6.2);
  STG->>DB: staged → APPROVED/NEW_CONTACT_CREATED; provenance; COMMIT
  STG-->>UI: {contact_id: 91, import_status: "NEW_CONTACT_CREATED"}
```

- **Local-wins (D-007/STAGED §6.2):** approval fills only NULL/empty canonical fields from the staged record; populated canonical fields are never overwritten; refusals are recorded in the staged row's `conflicts` and echoed in the approve response.
- **Smart Import variant:** when `import_policy=smart_import`, the gate runs programmatically at intake time — identical code path, no user in the loop; `review_first` (default, D-008) always lands in the queue first.
- **Invariants:** intake/scan write *only* staged (§1.10); reject/dismiss leave canonical untouched; approve is idempotent.

### 5.2 Duplicate merge with before-image audit (D-014)

```mermaid
sequenceDiagram
  participant UI as Duplicates view
  participant DUP as api/duplicates.py
  participant DB as crm.db
  UI->>DUP: GET /api/duplicates?tier=probable
  UI->>DUP: GET /api/duplicates/7 (field-level compare)
  UI->>DUP: POST /api/duplicates/7/merge {field_picks:{email:"left",phone:"right"}}
  DUP->>DB: BEGIN
  DUP->>DB: INSERT merge_audit (survivor=88, merged=91) + one before-image row per changed field
  DUP->>DB: UPDATE contacts SET picked fields (survivor keeps all other values, STAGED §6.6)
  DUP->>DB: UPDATE contacts SET deleted_at=now, merged_into_id=88 (loser)
  DUP->>DB: dedup index re-key; COMMIT
  DUP-->>UI: {survivor_id:88, merged_id:91, audit_id:"ma-18"}
```

- Same before-image mechanism is written by `POST /api/staged/{id}/merge-into-existing` (§4.10) and company merge (§3 #61) — one audit table for all merges.
- Undo = read before-image and reverse (Phase 5 scope decision in §7 Q6).

### 5.3 Reprocess (Phase 4)

```mermaid
sequenceDiagram
  participant UI as Processing History
  participant H as api/history.py
  participant JOB as job registry
  participant DB as crm.db
  UI->>H: GET /api/history (keyset)
  UI->>H: POST /api/history/12/reprocess
  H->>DB: DELETE processed_files WHERE file_id=12 (ledger row only)
  H->>JOB: enqueue reprocess job (file bytes re-read from stored path)
  H-->>UI: 202 {job_id:"j-a01", file_id:12}
  Note over JOB,DB: same pipeline as intake → staged rows only (§1.10);<br/>existing canonical rows are NOT re-touched — duplicates surface via dedup_status
  UI->>JOB: GET /api/jobs/j-a01 → done {staged: 38, warnings:[...]}
```

- Safe reprocess definition (parity row 25): never deletes canonical data, never re-approves; rows already staged for that file are matched by `source_file` + `raw_source_data` hash to avoid duplicate staging (Q6 affects this — §7).

### 5.4 Filtered export (Phase 6)

```mermaid
sequenceDiagram
  participant UI as Contacts / Reports
  participant X as api/reports.py
  participant DB as crm.db
  UI->>X: POST /api/export {format:"csv", entity:"contacts",
  UI->>X:   filters:[{field:"company",op:"eq",value:"Acme Pipes"}], Idempotency-Key: k9}
  X->>DB: keyset walk (WHERE company=:v, no OFFSET) — explicit column list
  X->>X: formula-sanitize every cell ('=+-@ prefix), RFC csv quoting
  X-->>UI: 200 text/csv + Content-Disposition attachment
  Note over UI,X: same request + k9 replayed → identical artifact, no regeneration (§1.9)<br/>selection_ids variant exports only checked rows; q variant exports the current search
```

- Export never runs from raw user input into a shell/subprocess; PDF via reportlab in-process (D-013).

---

## 6. Alignment & deviations

### 6.1 `app.py` route → target migration table

| Current route | `file:line` | Target | Fate |
|---|---|---|---|
| `GET /` | `app.py:85-87` | stays `app.py` | unchanged |
| `GET /api/status` | `app.py:90-103` | `api/system.py` | moved; + `external_requests_in_progress` (spec §4.4) |
| `GET /api/config` | `app.py:106-112` | — | **deleted → 410** (D-011) |
| `POST /api/config` | `app.py:115-125` | — | **deleted → 410** (D-011) |
| `POST /api/scan` | `app.py:128-133` | `api/intake.py` | moved; returns 202+job (§4.18) |
| `POST /api/intake` | `app.py:136-145` | `api/intake.py` | **body changes** JSON paths → multipart (D-009, §4.1) |
| `GET /api/jobs/{job_id}` | `app.py:148-151` | `api/jobs.py` | moved; **stub → real state** (P1-8) |
| `POST /api/jobs/{job_id}/cancel` | `app.py:154-157` | `api/jobs.py` | moved; **stub → real** |
| `GET /api/settings` | `app.py:160-163` | `api/settings.py` | moved; **masked output** (SEC-01) |
| `POST /api/settings` | `app.py:166-172` | `api/settings.py` | moved; allow-list + write-only key |
| `GET /api/contacts` | `app.py:175-183` | `api/contacts.py` | moved; **OFFSET→keyset**, `which` dropped (§7 Q2) |
| `PATCH /api/contacts/{which}/{id}` | `app.py:186-197` | `api/contacts.py` | **path shape change** (drop `{which}`) + column allow-list (SEC-04) |
| `DELETE /api/contacts/{which}/{id}` | `app.py:200-211` | `api/contacts.py` | path change; **hard→soft delete** (D-014) |
| `GET /api/export` | `app.py:214-228` | `api/reports.py` | **replaced by** `POST /api/export` (§4.23) |
| `POST /api/pick-folder` | `app.py:231-236` | `api/intake.py` | moved unchanged |
| `POST /api/open-folder` | `app.py:239-250` | `api/intake.py` | moved unchanged |
| `POST /api/test-llm` | `app.py:253-256` | `api/settings.py` | **replaced by** `POST /api/providers/{id}/test` (§4.13) |
| `POST /api/autostart` | `app.py:263-283` | `api/system.py` | moved unchanged |
| `/static/*` mount | `app.py:286` | stays `app.py` | unchanged |
| security-headers middleware | `app.py:32-38` | stays `app.py` | **extended with SEC-03** (§1.2) |
| startup (`db.init`, watcher) | `app.py:78-82` | stays `app.py` | unchanged |
| windowed-exe guard | `app.py:7-11` | stays `app.py` | unchanged |
| `_free_port` / `main()` | `app.py:289-311` | stays `app.py` | unchanged |
| `openapi_url=None` | `app.py:30` | stays `app.py` | unchanged (this doc is the contract) |

Breaking changes for existing consumers (`static/app.js`, `tests/test_app.py`) — each ships **in the same PR as its frontend/test update**: response shape of `GET /api/contacts`, path shapes of PATCH/DELETE contact, retirement of `/api/config`, masking of `/api/settings`, intake body format, jobs stub→real, `POST /api/test-llm` removal. QA P0-7's strict-xfails (key leak, dropzone transport) flip in those PRs (D-029).

### 6.2 Deliberate deviations from reference `api/`

| Reference behaviour | Where | Our deviation | Why |
|---|---|---|---|
| Settings stored **in-memory**, lost on restart | `api/settings.py:16` | persist in `config.json` via `config.py`, file `0600` | one store rule (D-011, D-028) |
| Settings GET returns raw `api_key` | `api/settings.py:47-49` | masked `has_key`/`api_key_set`, write-only key field | SEC-01 — reference is *worse* than target here |
| Supabase JWT on every router | `main.py:142-150` | **no auth layer at all** | loopback single-user by design (§1.1) |
| `POST /api/auth/upsert` | `api/auth.py:19` | not ported | no cloud identity (PRODUCT.md hard constraint) |
| Jobs endpoints also stubbed | `api/intake.py:170,176` | real job registry (§1.4) | QA P1-8 forbids stubs |
| Separate EML upload flow | `api/eml.py:219` | one universal intake only | "one of everything"; dropzone EML stages + writes `eml_emails` like folder scan (parity row 3) |
| Auto-push staged→CRM | `api/eml.py:319` | **deleted** | D-007: approval/Smart-Import gate only |
| `push`/`push-bulk` endpoints | `api/eml.py:482,500` | shape ported as `approve`/`approve-selected` | same semantics, staging vocabulary |
| CDN JSZip for ZIP | `frontend/index.html:15` (ref) | stdlib `zipfile` | no-CDN hard constraint (D-013) |
| Cloud `eml_store` Supabase wrappers | `services/eml_store.py` | not ported — SQLite only | one database (PRODUCT.md) |
| Session-keyed Data Table / upload-session KPIs | ref `frontend/app.js:1073,760` | DB-backed lists + `GET /api/dashboard` | target requires real DB values (P-15) |
| No `GET /api/contacts` at all | ref (parity row 13) | keyset list is net-new, not a port | target is ahead; port nothing |
| `PUT /api/settings` wholesale replace | `api/settings.py:52` | `POST` partial update + separate providers CRUD | avoids clobbering unrelated keys; chain is its own resource (spec §4.2) |

**Aligned on purpose:** multipart intake transport (reference `api/intake.py:30-37`; D-009 adopts it), per-file caps (50/10MB/100MB), provider allow-list + model regex + ollama-only `base_url` rule (ref `api/settings.py:61-66` → our §4.9 validators), call-log field shape (ref `api/calls.py` 1:1), CSV formula sanitize (ref `api/eml.py:416-421`), history/export session shape (ref `api/history.py:130,139,154,160` → our ledger variant), router-mount pattern with `prefix="/api"` (ref `main.py:142-150` minus `verify_token`).

### 6.3 Placement-map deviations (`CRM_FEATURE_PARITY.md` §4)

| Placement row | Contract's position | Deviation? |
|---|---|---|
| P-1 single orchestrator | intake/scan both return staged rows only; one `services/extraction.py` behind them | confirms |
| P-2 staging backend | `api/staging.py` + `staged_contacts` (STAGED §4.3) | confirms; D-006 makes the view question moot |
| P-4 settings | split: `api/settings.py` owns `/api/settings` **and** `/api/providers` (the row suggested keeping chain CRUD in `app.py`) | **deviation** — spec §4.2's dedicated providers surface wins over wholesale config writes |
| P-5 validation engine | surfaced via `/api/quality` (Phase 5) only — client-side duplicate logic deleted | confirms |
| P-6 dedup engine | read surfaces: `/api/duplicates`, `/api/staged/{id}/duplicates` | confirms |
| P-7 contacts API | keyset + `sort`/`filter`/`q` (§4.14) | confirms with the row's open question answered: **keyset, not offset** (STAGED §7.1) |
| P-8 companies | `api/companies.py`; company find-or-create **at approve time** (D-007) — intake does *not* upsert companies | **deviation from the row's recommendation** ("intake-time upsert") — D-007 overrides |
| P-9 search | `GET /api/search` incl. palette scope; FTS5 ships Phase 5 (D-020) | confirms, phase-split noted |
| P-10 emails | dropzone EML writes `eml_emails` too (deviation from *current* `intake.py:93-120`, not from the row) | confirms row's recommendation |
| P-11 calls | follow-ups as **separate resource** (`/api/follow-ups`) rather than only a `call_logs` column | **deviation** — column stays for call rows; standalone follow-ups need their own completion semantics (§7 Q5) |
| P-12 history | `GET /api/history` + reprocess (§4.19); `extraction_runs` stays unwritten for now | confirms, deferred |
| P-13 exports | `export.py` stays format owner; `api/reports.py` is the route layer; reportlab added to spec hiddenimports | confirms |
| P-14 jobs | real job registry, not deletion (§1.4) | answers the row's open question: **real async jobs** |
| P-15 dashboard | `GET /api/dashboard`, all SQL-derived | confirms |
| P-17 undo | soft-delete + merge before-images (D-014); import undo via staged/history | answers the row's "decide scope early" |
| P-18 tags/notes | `api/notes.py` (Phase 3) — schema still open (§7 Q5) | confirms, blocked on schema |
| P-19 `records`/`session_data` | not routed; mapping/history endpoints use `staged_contacts.raw_source_data` + `processed_files` | **open** — §7 Q6 |
| P-20 packaging | §2.2/§2.3 (spec hiddenimports + CI greps) | confirms D-010 |

### 6.4 Security cross-references

- **SEC-01** (masked keys, all four config/settings endpoints): implemented by §4.12/§4.13 and rows 3–16 of the catalogue; D-011 retirement of `/api/config` is the other half. Test: `test_settings_never_returns_api_key`.
- **SEC-02** (escaping `innerHTML` sinks): **frontend-owned**, not a wire contract — flagged here only so the Emails detail sanitizer (§4.20) and SEC-12 error codes (§1.3) are understood as its server-side prerequisites. CSP (SEC-14) lands Phase 6 with the inline-`onclick` removal.
- **SEC-03**: stated **once** in §1.2; no per-endpoint repetition anywhere.
- Related: SEC-04 → allow-lists in §4.15/§4.23 (and any future bulk update); SEC-05 → multipart intake §4.1; SEC-12 → error envelope §1.3; D-028 → `0600` config, size caps, `intake.py:78` NameError fix (same batch).

---

## 7. Open questions (max 8) — RESOLVED by D-032 (all ratified as assumed)

1. **Manual `POST /api/contacts` (§3 #44) vs D-007.** D-007 says canonical writes only via approval/Smart-Import — but that rule targets *import* paths (`intake.py`/`pipeline.py`). Confirm that user-authored CRUD is a permitted separate write path, or should manual create also land in staging first? (Contract assumes the former.)
2. **`which` parameter retirement timing.** `GET /api/contacts?which=crm|eml` and `{which}` in PATCH/DELETE (`app.py:175,186,200`) exist today; post-D-006 the EML side reads through `staged_contacts`/the `eml_contacts` view. Drop `which` outright in Phase 3 (contract's assumption), or keep a deprecated alias for one release for `static/app.js`?
3. **Job registry storage.** In-memory (fast, lost on restart — jobs orphan as `failed` on reload) vs ledger-backed in `processed_files`/`extraction_runs` (survives restart, more work). Contract assumes in-memory + capped `GET /api/jobs` list; P1-8 tests must be written against one of these.
4. **`approve-all-safe` predicate.** Contract assumes `review_status=READY AND dedup_status=UNIQUE`. Confirm — especially whether `NOT_CHECKED` dedup (first N rows before the dedup pass runs) may ever count as "safe" (recommend: no).
5. **Notes/tags/follow-ups schema (P-18, P-11 follow-up semantics).** No table exists; contract assumes `/api/notes`, `/api/tags`, `/api/views`, `/api/follow-ups` as first-class resources with `call_logs` keeping its `next_action_date` column. Database engineer must freeze this before Phase 3 routing starts.
6. **`records`/`session_data` keep-or-drop (STAGED Q9, P-19).** Reprocess/history/mapping-detect (§4.19, §3 #38) assume raw rows live on `staged_contacts.raw_source_data` + `processed_files`, with `records`/`session_data` left unrouted. If the legacy XLSX import-center UI is built instead, the history/template endpoints must read sessions — pick one before Phase 4.
7. **Retirement semantics for `/api/config`.** Contract assumes hard **410** with no alias (D-011 "retired"), frontend updated in the same PR. Confirm 410 rather than a secret-sanitizing compatibility alias — the alias would keep two surfaces alive and re-open the SEC-01 discussion later.
8. **Export synchronicity.** `POST /api/export` (§4.23) is synchronous with a 100k-row cap. If PDF/ZIP generation at that size exceeds ~5 s, should it move to the job model (§1.4)? Contract assumes sync + cap for v1.

---

## Report

- **Doc path:** `docs/INTERFACE_CONTRACTS.md` (this file; created read-only — no code, config, or test changes).
- **Endpoint count:** **86 catalogue rows = 84 API endpoints + 2 static/root rows**, of which **24 are Phase-2-critical (★)**; **25 detailed wire specs** in §4; **4 workflow sequences** in §5.
- **Top 3 contract risks:**
  1. **Jobs stub→real (P1-8) and intake body change (D-009) break existing consumers simultaneously** — `static/app.js` and `tests/test_app.py` depend on `app.py:136-157` shapes today; both must land in one PR each with their frontend/test update, or CI goes red via the strict-xfail ratchet (D-029).
  2. **`GET /api/contacts` response-shape migration (`{rows,page}` → `{items,next_cursor}`)** is the most-widely-consumed breaking change; any frontend missed in the swap silently renders an empty table rather than erroring.
  3. **The D-007 canonical-write gate is only as good as its static grep gate** — if `POST /api/contacts` (Q1) or company find-or-create creeps into intake before approval, the single-writer invariant that QA P0-2/P0-3 exist to prove is void; the contract's answer to Q1 must be settled before Phase 3 routing begins.
