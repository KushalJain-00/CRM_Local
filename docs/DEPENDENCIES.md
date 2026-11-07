# Dependencies — CRM_Local

Inventory of what the app actually imports vs what is declared, packaged, and tested. Read-only audit; no code changed.

## Dependency table

| Dependency | Kind (runtime/packaging/test) | Version pinned? | Used by | Notes |
|---|---|---|---|---|
| fastapi | runtime | ✅ `0.111.0` (requirements.txt:1) | app.py:15-17; tests/test_app.py:3 (`TestClient`) | Direct import; also supplies `TestClient` used by the test suite. |
| uvicorn | runtime | ✅ `0.29.0` (requirements.txt:2) | app.py:302,311 (lazy `import uvicorn` inside `main()`) | Lazy import — exactly what the spec's `hiddenimports` recipe covers (CRM_Local.spec:9-13). |
| httpx | runtime | ✅ `0.27.0` (requirements.txt:3) | llm.py:7; also required transitively by `fastapi.testclient` (tests/test_app.py:3) | LLM HTTP client; doubles as TestClient backend. |
| openpyxl | runtime | ✅ `3.1.2` (requirements.txt:4) | parse.py:6; export.py:4-6; tests/test_parse.py:1; tests/test_export.py:3 | XLSX read + write (the only export format shipping today, app.py:214). |
| xlrd | runtime | ✅ `2.0.1` (requirements.txt:5) | services/parser.py:1 | Legacy `.xls` parsing only (xlrd 2.x dropped XLSX). |
| PyMuPDF | runtime | ✅ `1.28.2` (requirements.txt:6) | services/parser.py:5 (`import fitz`) | PDF text extraction. Import name (`fitz`) ≠ package name (`PyMuPDF`) — packaging-relevant. No pypdf/pdfplumber anywhere. |
| pydantic | runtime (direct import) | ❌ undeclared (transitive of fastapi) | app.py:18 (`BaseModel`) | **Imported but not declared.** Installed 2.14.3 in `venv/` vs 2.13.5 in system python — already drifting between environments. |
| python-multipart | runtime (conditional, future D-009) | ❌ not declared | none today — no `Form`/`File`/`UploadFile` anywhere (grep: zero hits) | Installed anyway: venv 0.0.33, system 0.0.9 — **installed but undeclared**. Becomes required when multipart intake lands; must add to requirements.txt + spec hiddenimports in the same change (INTERFACE_CONTRACTS.md:178). |
| reportlab | runtime (future D-013) | ❌ not declared | none today (zero imports) | Installed 4.1.0 in system python only — **installed but undeclared**. Needed for PDF export (CRM_FEATURE_PARITY.md:357; INTERFACE_CONTRACTS.md:543). |
| pytest | test | ✅ `9.1.1` (requirements-dev.txt:2, via `-r requirements.txt` line 1) | tests/conftest.py:4 and every `tests/test_*.py` | **Not installed in `venv/`** — `venv/bin/python -m pytest` → `No module named pytest`. Only the system python (3.14.7) has it. |
| PyInstaller | packaging | ❌ unpinned (`pip install pyinstaller`, windows-build.yml:27) | CRM_Local.spec build (windows-build.yml:33) | Not installed locally either; CI-only, floating version. |
| PyInstaller spec (`CRM_Local.spec`) | packaging | n/a | Analysis on `app.py` (CRM_Local.spec:4); `datas=[("static","static")]` (:7); `hiddenimports` = 5 uvicorn modules only (:8-14); `excludes=["tkinter.test","test"]` (:17) | All other current runtime deps are direct, statically analysable imports — no hiddenimports needed today. |

**Stdlib deliberately used instead of third-party (verified, not assumed):**

- **EML**: stdlib `email` — pipeline.py:7-8, services/eml_processor.py:3-4. No `extract-msg`.
- **CSV**: stdlib `csv` — parse.py:2, services/adapters/csv.py:3. No pandas.
- **PDF**: PyMuPDF (`fitz`) only — services/parser.py:5. No pypdf/PyPDF2/pdfplumber.
- **ZIP/VCF (D-013, future)**: planned stdlib `zipfile` + native vCard writer, no CDN JSZip (INTERFACE_CONTRACTS.md:543,706).

## Network posture

**Verdict: clean — zero CDN/remote URLs in `static/`.** Grep for `http(s)://|cdn|fonts.google|unpkg|jsdelivr|cdnjs` across `static/` returns nothing; the only asset references are local (`static/index.html:7` `href="/static/style.css"`, `static/index.html:205` `src="/static/app.js"`).

## Gaps

1. **Missing hiddenimports (D-009/D-013):** `CRM_Local.spec:8-14` lists only the uvicorn recipe. `reportlab` and `python-multipart` are not in `hiddenimports` — fine *today* (neither is imported), but D-009 (multipart intake) and D-013 (PDF export) both require adding them to `requirements.txt` **and** `hiddenimports` in the same change (INTERFACE_CONTRACTS.md:178). Watch item: PyMuPDF's `fitz` import name relies on PyInstaller's third-party hook (pulled in by CI's `pip install pyinstaller`), not on this spec.
2. **Undeclared / installed-but-undeclared imports:**
   - `pydantic` imported directly (app.py:18) but not in requirements.txt — transitive only, already at two different versions across environments (venv 2.14.3 vs system 2.13.5).
   - `python-multipart` (venv 0.0.33, system 0.0.9) and `reportlab` (system 4.1.0) are installed locally yet declared nowhere — local env ≠ CI env (CI installs requirements.txt only, ci.yml:27-28).
   - No declared-but-never-imported dependency: all 6 entries in requirements.txt are imported (fastapi app.py:15; uvicorn app.py:302; httpx llm.py:7; openpyxl parse.py:6; xlrd services/parser.py:1; PyMuPDF services/parser.py:5).
3. **Version skew (test/CI vs local):**
   - CI matrix is Python **3.11/3.12** (ci.yml:14) and **3.12** for the Windows build (windows-build.yml:20); local is **3.14.7** — CI never exercises the version you develop on, and vice versa.
   - `pytest==9.1.1` is pinned (requirements-dev.txt:2) but **absent from `venv/`** — local test runs silently fall back to system python, so "tests pass locally" doesn't prove the venv the app runs from.
   - PyInstaller is floating in CI (windows-build.yml:27); pydantic is floating everywhere.

## Verdict

**Mostly clean split, but "no" overall — three actions before it's trustworthy:**

The *structure* is right: runtime pins in `requirements.txt`, test on top via `-r` in `requirements-dev.txt` (no duplicate pins), packaging isolated in `CRM_Local.spec`, and zero CDN references. What breaks the "clean" verdict is environment/CI divergence, not the file layout.

**Actions:**
1. Run `venv/bin/pip install -r requirements-dev.txt` so the venv (the runtime you ship) actually has pytest — today local tests run on system python 3.14.7, not in the venv.
2. Pin `pydantic` in requirements.txt (it's a direct import, app.py:18) and decide the CI matrix: add `3.14` alongside 3.11/3.12, or document that local 3.14.7 is unsupported by CI.
3. When D-009/D-013 land: add `python-multipart` / `reportlab` to `requirements.txt` **and** `CRM_Local.spec` `hiddenimports` in the same PR (INTERFACE_CONTRACTS.md:178), and remove the stray undeclared installs from local environments so local == CI.
