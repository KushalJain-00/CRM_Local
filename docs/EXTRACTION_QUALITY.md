# Extraction quality — release 1.0.0 (2026-11-13)

Synthetic, PII-free benchmark corpus in `tests/corpus/` (10 files, 17
contacts), measured with `tests/test_extraction_quality.py` on the
**deterministic Layer-1 path** (no AI configured). Run:
`venv/bin/python -m pytest tests/test_extraction_quality.py -s`

## Measured results (this build)

| Field | Precision | Recall | tp/fp/fn |
|---|---|---|---|
| name | 1.00 | 1.00 | 17/0/0 |
| email_primary | 1.00 | 1.00 | 16/0/0 |
| phone_primary | 1.00 | 1.00 | 17/0/0 |
| company | 1.00 | 1.00 | 9/0/0 |
| city | 1.00 | 1.00 | 5/0/0 |
| pincode | 1.00 | 1.00 | 5/0/0 |

Contacts: expected 17, extracted 17, matched 17. Fabricated values: **none**
(every extracted email/phone verified to appear in the source text).
Safety invariants asserted on every run: zero invented emails, zero invented
phones, zero cross-record email↔phone pairings.

## What this number means — and what it does not

- The corpus is **synthetic and co-designed with the extractor**; perfect
  scores prove the pipeline does not fabricate, mis-pair or drop records on
  representative inputs, and guard against regressions. They do **not**
  predict accuracy on real client mailboxes, scanned PDFs without a text
  layer, or pathological exports.
- AI-assisted extraction is **not** measured here; it is covered by
  contract-validation unit tests (`tests/test_contract.py`,
  `tests/test_chunking.py`) and mocked provider tests. Live-provider quality
  is **NOT VERIFIED**.
- Known limits: scanned PDFs without a text layer yield zero text (input is
  rejected with an actionable error, not silently accepted); EML contacts
  mentioned only in quoted history are deliberately not extracted (by the
  master-prompt rule and by the deterministic fallback's From-header focus).

## Also fixed while building the corpus

- Header-mapping now recognises "Person" as a name column.
- Per-sheet header inference now takes the **union of all row keys**, so
  records whose optional fields (City/Pincode) appear only in later rows are
  no longer dropped at the mapping stage.

## Ground truth and corpus regeneration

`tests/corpus/ground_truth.json` is the reference. Files were generated
synthetically; committed binaries (.xls/.xlsx/.pdf) are safe. Do not add real
client data to the corpus.
