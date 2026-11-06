# services/adapters/xlsx.py — XLSX extraction adapter
"""Handles .xlsx files (openpyxl read-only)."""
import os
from . import NormalizedContact, ExtractionResult


class XlsxAdapter:
    name = "xlsx"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".xlsx")

    async def extract(self, file_path: str) -> ExtractionResult:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            contacts = []
            warnings = []
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    continue
                headers = [str(h).strip() if h is not None else f"Col_{i}" for i, h in enumerate(rows[0])]
                for i, row in enumerate(rows[1:], start=2):
                    nc = NormalizedContact(source_file=os.path.basename(file_path), source_row=i)
                    for j, val in enumerate(row):
                        if j < len(headers) and val is not None:
                            h = headers[j].lower().strip()
                            if "name" in h or "contact" in h:
                                nc.name = str(val).strip()
                            elif "email" in h:
                                nc.email_primary = str(val).strip().lower()
                            elif "phone" in h or "mobile" in h:
                                nc.phone_primary = str(val).strip()
                            elif "company" in h:
                                nc.company = str(val).strip()
                            elif "designation" in h or "title" in h or "position" in h:
                                nc.designation = str(val).strip()
                            elif "address" in h:
                                nc.address = str(val).strip()
                            elif "city" in h:
                                nc.city = str(val).strip()
                            elif "pincode" in h or "zip" in h or "postal" in h:
                                nc.pincode = str(val).strip()
                            elif "website" in h or "url" in h:
                                nc.website = str(val).strip()
                    if nc.name or nc.email_primary or nc.phone_primary:
                        contacts.append(nc)
            wb.close()
            return ExtractionResult(contacts=contacts, adapter="xlsx", local_only=True)
        except Exception as e:
            return ExtractionResult(contacts=[], warnings=[str(e)], adapter="xlsx", local_only=True)


