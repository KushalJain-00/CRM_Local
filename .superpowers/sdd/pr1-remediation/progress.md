# SDD ledger — plan: /tmp/opencode/pr1-remediation-plan.md
Branch: fix/pr1-remediation (origin/main 8760b31 + redesign 7051401). PR#1 head = pull1 6b5724f (redesign + junk commits 87a2bd1, 32cdc12 — not touched).
Pre-existing uncommitted static/app.js diff from prior session already covers Fix 1 (API_BASE), Fix 5 (settings esc), Fix 6 (csvCell), Fix 7 (data-sort fallback retained).
Plan tasks: 1 API_BASE, 2 multipart upload, 3 xfail ratchet, 4 charts→tables (D-012), 5 XSS, 6 CSV injection, 7 sort data-attrs, 8 palette close sync, 9 regression tests, 10 full verification + CI.

Pre-flight: Tasks 1,5,6,7 all edit static/app.js settings/csv/sort areas — no interface conflicts; Task 4 removes chart fns also referenced by Task 2's untouched sections. No shared interfaces between tasks.

## Completion — 2026-11-10
- Task 1: API_BASE fixed — all fetch calls single `/api/` prefix (grep clean of `/api/api/`).
- Task 2: api/intake.py — real UploadFile bytes via _spool_uploads/_unspool (size caps → 413, cleanup in finally).
- Task 3: tests/test_ratchet.py — xfail removed on exportContacts/filterContacts (D-029 compliant now).
- Task 4: chart fns/CSS `--chart-*`/`chart-*` ids all removed; analytics renders tables (D-012).
- Task 5: settings responses esc() before innerHTML (api_key masked JSON only remaining in DOM).
- Task 6: csvCell() guard before CSV build/upload (regression test, node-skipped).
- Task 7: 11 data-sort attrs in index.html + updateSortUI() in app.js.
- Task 8: palette openPalette() dialog guard + confirmDialog close→paletteClose() sync.
- Task 9: tests/test_pr1_remediation.py — 15 tests, all pass (node-gated one skips w/o node).
- Task 10: full suite 256 passed / 1 xfailed (BUG-SEC-06 magic-bytes, intentionally xfail, out of scope); node --check clean; live uvicorn smoke: / 200, /api/health ok, /api/settings chain.
- NOT FIXED (reported): frontend Contacts view calls /api/contacts*, /api/emails — routes do not exist in backend (D-010 phase 2/3 owner); frontend still passes which=crm (D-032 drops in Phase 3).
