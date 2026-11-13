# CRM Local — Release Notes

## 1.1.0

Second client release. Local-first CRM extraction for Windows.

### Prompt intelligence

- Master extraction prompts rewritten: identity precedence (From > Reply-To >
  signature), evidence grades for `field_evidence`, signature/forward/quoted-
  history handling, automated and organisational-mailbox behaviour (name: null),
  injection hardening, and an evaluator suite (23 assembly/extraction assertions
  on a PII-free synthetic corpus).
- Layer-1 fix: deterministic MIME headers are authoritative when no signature
  is present — a body-mentioned third party is never preferred over the From
  identity.
- Prompt settings now surface the server's 422 details verbatim when a save
  is rejected by the validator.

### Untangle refactor (structural, behavior-preserving)

- One identity-key implementation (`services/keys.py`) used by every writer —
  staged rows, approval, edits, chunking, migrations. Fixes the `name_key`
  divergence and stored-key drift across paths.
- One extraction lifecycle (`services/extract.py`) shared by upload and folder
  scan — no more diverging merge implementations; EML parsed once; deterministic
  results never discarded; unmatched EMLs stage as NEEDS_REVIEW; recipients
  (To/Cc/Bcc) now persisted for uploaded emails.
- Shared infrastructure: one limits module, one data-directory implementation,
  one database connection factory, one reliability specification.
- Dead code removed: write-only DedupIndex, legacy upsert/insert/push-to-CRM
  paths, retired /api/config masking leftovers, unreferenced modules.
- Frontend: one API client with a real wait queue (it previously rejected
  under contention), one badge factory, one view-dispatch table, per-table
  density preferences that actually persist across reload, dead state removed.

### Packaging

- Windows build via PyInstaller 6.11.1 on Python 3.12 on GitHub Actions
  (windows-latest), Inno Setup installer. Build verified: workflow run
  43484573858 — all stages green (tests, executable, installer, SHA256SUMS).
  Artifacts: CRM_Local.exe (47,756,633 B, sha256 D83DC91C585A992F87582EDD5ADB79B1E7D5A5C9555D3D163066E80CC8FC72C0)
  and CRM_Local-Setup.exe (48,873,695 B,
  sha256 286CB8D6E8699046F024D4A7D9793438C8F0CB899AECF765BC7219E306FAF6EC).
- The frozen build keeps the release 1.0.0 data directory (POSIX
  ~/.crm_local, Windows %APPDATA%/CRM_Local) and still runs its first-launch
  self-verification.
- PDF parsing uses pdfplumber (MIT) and its permissively-licensed
  dependencies — no copyleft obligations.

### Quality gates

Verified for this build:

- 400 tests green, 1 xfailed (Python 3.14 locally; CI matrix 3.11/3.12;
  Windows build run 43484573858 green, including Inno Setup installer).
- Contract audit clean (`tools/contract_audit.py`): all 68 inline handlers
  defined; no missing element ids; zero external requests.
- Synthetic-corpus extraction evaluation (PII-free, `tests/evaluation/`):
  Layer-1 and mocked-AI paths — 20 documents, all expectations met.
- Orchestrator parity: upload intake and folder scan stage byte-identical
  contacts (`tests/test_extract_parity.py`).
- Browser E2E: 26 screens; 0 console errors; 0 failed/external requests.
- Failure contract verified against an unreachable provider: extraction
  proceeds on deterministic Layer-1, the degraded-mode warning is surfaced,
  and no error surfaces to the requestor.

Not verified for this build:

- Live LLM provider quality. No live provider call was made (no cloud
  credentials configured; the candidate local model could not be loaded in the
  release environment: 7 GB RAM, no GPU, the Ollama model never started).
  Provider-quality claims are limited to mocked protocol tests and
  deterministic evaluation.
- Windows installation testing on a clean machine. This pipeline verifies
  compile, executable presence and installer construction; it does not
  execute the installer.

### Known limitations (carried over)

- Scanned PDFs without a text layer are not OCR'd.
- Deterministic Layer-1 extraction of free-form prose finds fewer fields than
  structured exports; configure a provider for best results on messy files.
- Watch mode is manual in this release.
- Windows SmartScreen may flag the unsigned installer (no code-signing
  certificate was provided for this build).
- Migrations to existing databases are explicit, backed up and transactional —
  they are never applied silently.

### Outstanding checks before release

- Merge to main and the v1.1.0 tag have NOT been performed (owner decision
  pending Windows build verification).
- Live provider validation remains an owner task; see
  `docs/PROVIDER_VALIDATION.md`.

## 1.0.0

First client release. Local-first CRM extraction for Windows.

### Extraction

- Six source formats: CSV, XLSX, XLS, PDF, TXT, EML — one review pipeline.
- Multi-sheet workbooks with per-sheet header mapping (merged cells,
  multi-row headers, repeated headers tolerated).
- PDF: table extraction plus labeled-line fallback with per-record pairing
  (an email is never paired with the wrong phone number).
- EML: From-header display name wins over guessed signature names; quoted
  history and disclaimers are not treated as the sender's identity.
- Staged review: nothing reaches the CRM without explicit approval.
  Exact/probable duplicates, conflicts and invalid values are flagged, not hidden.
- Provenance everywhere: source file, row, sheet, field evidence, confidence.

### Reliability and safety

- Provider chain with priority order, bounded retries, exponential backoff
  with jitter, Retry-After support, per-attempt and overall deadlines,
  circuit breaker, and failover in configured order.
- API keys are masked everywhere; configuration is owner-only; loopback-only
  server with Origin/Host validation.
- Fresh installs self-provision the full schema; upgrades to an existing
  database are explicit, backed up, and transactional.
- No charts anywhere (product constraint) — summaries and tables only.

### Packaging

- Windows build via PyInstaller 6.11.1 on Python 3.12; Inno Setup installer.
  Build verified: GitHub Actions run 43322333133 (main @ 7739f83) — all steps
  green; artifacts CRM_Local.exe (47,762,343 B) and CRM_Local-Setup.exe
  (48,880,259 B), SHA256 published in the build's SHA256SUMS.txt.
- The frozen build self-verifies at first launch (database, schema, static
  assets, staging pipeline).
- PDF parsing uses pdfplumber (MIT) and its permissively-licensed
  dependencies (pdfminer.six, pypdfium2, Pillow) — no copyleft obligations.

### Quality gates

- 332 tests green on a fresh venv install (Python 3.14; CI matrix 3.11/3.12).
- Deterministic extraction scores 17/17 contacts on a synthetic corpus with
  zero fabricated values (tests/corpus/). Layer-1 falls back safely when AI
  is unavailable.
- Dependencies: all runtime libraries are MIT/BSD/Apache-class; pdfplumber
  replaced PyMuPDF. See THIRD_PARTY_NOTICES.md.

### Known limitations

- Scanned PDFs without a text layer are not OCR'd.
- Layer-1 (no-AI) extraction of free-form prose finds fewer fields than
  structured exports; configure a provider for best results on messy files.
- The folder-scan "watch" mode is manual in this release.
- Windows SmartScreen may flag the unsigned installer (no code-signing cert
  was provided for this build).
- Live provider verification (real API calls) was not performed in the
  release environment; all provider protocols are covered by mocked tests.
