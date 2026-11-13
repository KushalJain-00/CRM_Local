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
