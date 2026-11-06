# services/adapters/pdf.py — PDF extraction adapter
"""Wraps services/parser.py parse_pdf for .pdf files."""
import os
from . import NormalizedContact, ExtractionResult


class PdfAdapter:
    name = "pdf"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".pdf")

    async def extract(self, file_path: str) -> ExtractionResult:
        from services.parser import parse_pdf
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            result = parse_pdf(content)
            contacts = []
            for i, row in enumerate(result.get("rows", [])):
                nc = NormalizedContact(source_file=os.path.basename(file_path), source_row=i + 2)
                headers = result.get("headers", [])
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
                        elif "designation" in h or "title" in h or "position" in h:
                            nc.designation = str(val).strip() if val else None
                        elif "address" in h:
                            nc.address = str(val).strip() if val else None
                        elif "city" in h:
                            nc.city = str(val).strip() if val else None
                        elif "pincode" in h or "zip" in h or "postal" in h:
                            nc.pincode = str(val).strip() if val else None
                        elif "website" in h or "url" in h:
                            nc.website = str(val).strip() if val else None
                if nc.name or nc.email_primary or nc.phone_primary:
                    contacts.append(nc)
            return ExtractionResult(contacts=contacts, adapter="pdf", local_only=True)
        except Exception as e:
            return ExtractionResult(contacts=[], warnings=[str(e)], adapter="pdf", local_only=True)


