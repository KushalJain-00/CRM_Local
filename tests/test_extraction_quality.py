# Extraction-quality benchmark — synthetic corpus, no PII.
# Ground truth: tests/corpus/ground_truth.json (documents per-file expected
# contacts). Runs the real adapters and reports field-level precision/recall.
# Safety invariants are hard assertions; quality metrics are reported, with
# conservative floors so regressions fail the build.
import asyncio
import json
import re
from pathlib import Path

from services.adapters import get_adapter

CORPUS = Path(__file__).parent / "corpus"
FILES = CORPUS / "files"
TRUTH = json.loads((CORPUS / "ground_truth.json").read_text())

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
FIELDS = ["name", "email_primary", "phone_primary", "company", "city", "pincode"]

def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")

def _load(file_name: str):
    adapter = get_adapter(str(FILES / file_name))
    result = asyncio.run(adapter.extract(str(FILES / file_name)))
    return result

def _match(found: list, expected: list[dict]) -> list[tuple]:
    """Greedy one-to-one match: by email first, then name; else by order."""
    pairs, used = [], set()
    for exp in expected:
        best, best_score = None, 0.0
        for j, got in enumerate(found):
            if j in used:
                continue
            score = 0.0
            if exp.get("email_primary") and got.email_primary == exp["email_primary"]:
                score += 2.0
            if exp.get("name") and got.name and got.name.strip().lower() == exp["name"].strip().lower():
                score += 1.0
            if exp.get("phone_primary") and got.phone_primary and \
                    _digits(got.phone_primary) == _digits(exp["phone_primary"]):
                score += 1.0
            if score > best_score:
                best, best_score = j, score
        if best is not None and best_score > 0:
            pairs.append((expected.index(exp), best))
            used.add(best)
    return pairs

def _source_text(path: Path) -> str:
    """Extract all human-readable text from a corpus file (per format)."""
    ext = path.suffix.lower()
    if ext == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        return "\n".join(str(c) for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for c in row if c is not None)
    if ext == ".xls":
        import xlrd
        wb = xlrd.open_workbook(str(path))
        out = []
        for sh in wb.sheets():
            for r in range(sh.nrows):
                out.extend(str(sh.cell_value(r, c)) for c in range(sh.ncols))
        return "\n".join(out)
    if ext == ".pdf":
        import io
        import pdfplumber
        with pdfplumber.open(io.BytesIO(path.read_bytes())) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    return path.read_bytes().decode("utf-8", errors="ignore")

def _harvest():
    report = {}
    totals = {f: {"tp": 0, "fp": 0, "fn": 0} for f in FIELDS}
    fabrication = []
    for file_name, expected in TRUTH.items():
        result = _load(file_name)
        found = result.contacts
        pairs = _match(found, expected)
        matched_found = {fb for _, fb in pairs}
        file_stats = {
            "expected": len(expected), "found": len(found),
            "matched": len(pairs), "fields": {},
        }
        for fi, ei in [(e, g) for e, g in pairs]:
            pass  # filled below
        for file_idx, got_idx in pairs:
            exp, got = expected[file_idx], found[got_idx]
            for field in FIELDS:
                exp_val = (exp.get(field) or None)
                got_val = getattr(got, field, None)
                if field == "phone_primary" and got_val:
                    ok = _digits(str(got_val)) == _digits(str(exp_val))
                else:
                    ok = (str(got_val).strip().lower() == str(exp_val).strip().lower()) if exp_val else not got_val
                key = totals[field]
                if exp_val:
                    if ok:
                        key["tp"] += 1
                    else:
                        key["fp"] += 1
                        key["fn"] += 1
                else:
                    if got_val:
                        key["fp"] += 1  # invented where source says missing
        # unmatched expected records count as false negatives
        matched_exp = {ei for ei, _ in pairs}
        for i, exp in enumerate(expected):
            if i not in matched_exp:
                for field in FIELDS:
                    if exp.get(field):
                        totals[field]["fn"] += 1
        # fabrication guard: every extracted value must exist in the source text
        source = _source_text(FILES / file_name)
        for got in found:
            if got.email_primary and got.email_primary.lower() not in source.lower():
                fabrication.append(f"{file_name}: invented email {got.email_primary!r}")
            if got.phone_primary and _digits(got.phone_primary) not in _digits(source):
                fabrication.append(f"{file_name}: invented phone {got.phone_primary!r}")
        file_stats["fabrication"] = [f for f in fabrication if f.startswith(file_name)]
        report[file_name] = file_stats
    return report, totals, fabrication

def test_extraction_corpus_report():
    report, totals, fabrication = _harvest()
    print("\n\n=== EXTRACTION QUALITY REPORT (deterministic Layer-1) ===")
    for f in FIELDS:
        t = totals[f]
        prec = t["tp"] / (t["tp"] + t["fp"]) if (t["tp"] + t["fp"]) else 1.0
        rec = t["tp"] / (t["tp"] + t["fn"]) if (t["tp"] + t["fn"]) else 1.0
        print(f"{f:14s} precision={prec:.2f} recall={rec:.2f}  (tp={t['tp']} fp={t['fp']} fn={t['fn']})")
    total_found = sum(r["found"] for r in report.values())
    total_expected = sum(r["expected"] for r in report.values())
    total_matched = sum(r["matched"] for r in report.values())
    print(f"contacts: expected={total_expected} extracted={total_found} matched={total_matched}")
    print("fabrication:", fabrication or "none")
    for name, st in report.items():
        print(f"  {name}: expected={st['expected']} found={st['found']} matched={st['matched']}")
    (CORPUS / "report.json").write_text(json.dumps(
        {"files": report,
         "fields": {f: totals[f] for f in FIELDS}}, indent=2))
    # Hard safety assertions
    assert fabrication == [], f"fabricated values detected: {fabrication}"
    # Conservative quality floors (deterministic Layer-1, synthetic corpus)
    email = totals["email_primary"]
    email_recall = email["tp"] / (email["tp"] + email["fn"]) if (email["tp"] + email["fn"]) else 1.0
    assert email_recall >= 0.9, f"email recall {email_recall:.2f} below floor"
    phone = totals["phone_primary"]
    phone_recall = phone["tp"] / (phone["tp"] + phone["fn"]) if (phone["tp"] + phone["fn"]) else 1.0
    assert phone_recall >= 0.7, f"phone recall {phone_recall:.2f} below floor"
    assert total_matched >= 0.9 * total_expected
