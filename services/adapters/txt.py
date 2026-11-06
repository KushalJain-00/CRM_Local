# services/adapters/txt.py — TXT extraction adapter (phone list)
"""Handles .txt files (phone list parsing)."""
import os, re
from . import NormalizedContact, ExtractionResult


class TxtAdapter:
    name = "txt"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".txt")

    async def extract(self, file_path: str) -> ExtractionResult:
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                lines = f.readlines()
            contacts = []
            for i, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue
                # Try to extract phone numbers
                phones = re.findall(r"(?:\+91[\s\-]?)?[6-9]\d{9}|\+\d{1,3}[\s\-]?\d{7,14}", line)
                if phones:
                    nc = NormalizedContact(
                        phone_primary=phones[0].strip(),
                        source_file=os.path.basename(file_path),
                        source_row=i + 1,
                        field_origin={"phone_primary": "local"},
                    )
                    contacts.append(nc)
            return ExtractionResult(contacts=contacts, adapter="txt", local_only=True)
        except Exception as e:
            return ExtractionResult(contacts=[], warnings=[str(e)], adapter="txt", local_only=True)


