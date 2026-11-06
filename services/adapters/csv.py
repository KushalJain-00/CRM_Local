# services/adapters/csv.py — CSV extraction adapter
"""Handles .csv files (header mapping + row-to-contact)."""
import os, csv, io
from . import NormalizedContact, ExtractionResult


class CsvAdapter:
    name = "csv"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".csv")

    async def extract(self, file_path: str) -> ExtractionResult:
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                headers = next(reader, [])
                rows = list(reader)
            contacts = []
            for i, row in enumerate(rows):
                nc = NormalizedContact(source_file=os.path.basename(file_path), source_row=i + 2)
                for j, val in enumerate(row):
                    if j < len(headers):
                        h = headers[j].lower().strip()
                        if "name" in h or "contact" in h:
                            nc.name = str(val).strip() if val else None
                        elif "email" in h:
                            nc.email_primary = str(val).strip().lower() if val else None
                        elif "phone" in h or "mobile" in h:
                            nc.phone_primary = str(val).strip() if val else None
                        elif "company" in h:
                            nc.company = str(val).strip() if val else None
                        elif "designation" in h or "title" in h:
                            nc.designation = str(val).strip() if val else None
                        elif "address" in h:
                            nc.address = str(val).strip() if val else None
                        elif "city" in h:
                            nc.city = str(val).strip() if val else None
                        elif "pincode" in h or "zip" in h:
                            nc.pincode = str(val).strip() if val else None
                        elif "website" in h or "url" in h:
                            nc.website = str(val).strip() if val else None
                if nc.name or nc.email_primary or nc.phone_primary:
                    contacts.append(nc)
            return ExtractionResult(contacts=contacts, adapter="csv", local_only=True)
        except Exception as e:
            return ExtractionResult(contacts=[], warnings=[str(e)], adapter="csv", local_only=True)


