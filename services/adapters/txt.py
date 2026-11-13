# services/adapters/txt.py — TXT extraction adapter
"""Handles .txt files: phones, emails, and a best-effort name from each line.

Records group per line — a line with an email or phone yields one staged
contact. Anything ambiguous is flagged by the validators and lands in
NEEDS_REVIEW; nothing is dropped silently, nothing is invented.
"""
import os, re
from . import NormalizedContact, ExtractionResult
from services.keys import EMAIL_RE as _EMAIL_RE
# Loose candidate; digit count is validated after extraction (7–15 digits).
_PHONE_CAND = re.compile(r"(?:\+\d{1,3}[\s\-.()/]*)?(?:\(?\d[\s\-.()/]*){7,14}\d")
_NAME_HINT = re.compile(r"\b(?:mr|mrs|ms|dr)\.?\s+", re.I)


def _phones(line: str) -> list[str]:
    out = []
    for m in _PHONE_CAND.finditer(line):
        raw = m.group(0).strip()
        digits = re.sub(r"\D", "", raw)
        if 7 <= len(digits) <= 15:
            out.append(raw)
    return out


def _name_from_line(line: str) -> str | None:
    # Drop emails and phones, then split on separators and pick the most
    # name-looking segment (2–4 alphabetic words, optional honorific).
    text = _EMAIL_RE.sub(" ", line)
    text = _PHONE_CAND.sub(" ", text)
    for part in re.split(r"[—–|•;,]", text):
        part = part.strip(" -–—")
        part = _NAME_HINT.sub("", part).strip()
        words = part.split()
        if 2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-z][A-Za-z.'-]*", w) for w in words):
            return part[:80]
    return None


class TxtAdapter:
    name = "txt"
    MAX_TABLE_LINES = 500  # AI-assist table is capped; deterministic path is unaffected

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".txt")

    async def extract(self, file_path: str) -> ExtractionResult:
        try:
            with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
                lines = f.readlines()
            contacts = []
            for i, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue
                emails = _EMAIL_RE.findall(line)
                phones = _phones(line)
                if not emails and not phones:
                    continue
                nc = NormalizedContact(
                    name=_name_from_line(line),
                    email_primary=emails[0].lower() if emails else None,
                    email_secondary=emails[1].lower() if len(emails) > 1 else None,
                    phone_primary=phones[0] if phones else None,
                    phone_secondary=phones[1] if len(phones) > 1 else None,
                    source_file=os.path.basename(file_path),
                    source_row=i + 1,
                    field_origin={k: "local" for k, v in
                                  (("email_primary", emails), ("phone_primary", phones))
                                  if v},
                )
                contacts.append(nc)
            warnings = []
            if len(lines) > self.MAX_TABLE_LINES:
                warnings.append(f"file has {len(lines)} lines; AI assist sees the first {self.MAX_TABLE_LINES}")
            table = {
                "sheet": os.path.basename(file_path),
                "headers": ["line"],
                "rows": [{"_row": i + 1, "_sheet": "TXT", "line": ln.rstrip("\n")}
                         for i, ln in enumerate(lines[:self.MAX_TABLE_LINES]) if ln.strip()],
            }
            return ExtractionResult(contacts=contacts, warnings=warnings,
                                    adapter="txt", local_only=True, table=table)
        except Exception as e:
            return ExtractionResult(contacts=[], warnings=[str(e)], adapter="txt", local_only=True)
