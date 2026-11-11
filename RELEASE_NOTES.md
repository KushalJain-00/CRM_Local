# CRM Local — Release Notes

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
- The frozen build self-verifies at first launch (database, schema, static
  assets, staging pipeline).
- Known packaging note: PyMuPDF (PDF parsing) is dual-licensed AGPL-3.0 /
  Artifex commercial. See THIRD_PARTY_NOTICES.md before distributing.

### Known limitations

- Scanned PDFs without a text layer are not OCR'd.
- Layer-1 (no-AI) extraction of free-form prose finds fewer fields than
  structured exports; configure a provider for best results on messy files.
- The folder-scan "watch" mode is manual in this release.
- Windows SmartScreen may flag the unsigned installer (no code-signing cert
  was provided for this build).
- Live provider verification (real API calls) was not performed in the
  release environment; all provider protocols are covered by mocked tests.
