# services/adapters/eml.py — EML extraction adapter
"""Wraps services/eml_processor.py for .eml files."""
import os
from . import NormalizedContact, ExtractionResult


class EmlAdapter:
    name = "eml"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".eml")

    async def extract(self, file_path: str) -> ExtractionResult:
        from services.eml_processor import parse_eml_bytes, extract_local_fields, build_llm_prompt, merge_fields, FIELD_KEYS
        try:
            with open(file_path, "rb") as f:
                raw = f.read()
            parsed = parse_eml_bytes(raw, os.path.basename(file_path))
            local = extract_local_fields(parsed)
            # Layer 1 only (no LLM in adapter; LLM enrichment handled by orchestrator)
            contact = merge_fields(local, None)
            contact["to_emails"] = parsed.to_emails
            contact["cc_emails"] = parsed.cc_emails
            contact["bcc_emails"] = parsed.bcc_emails
            nc = NormalizedContact(
                name=contact.get("name"),
                email_primary=contact.get("email"),
                phone_primary=contact.get("phone_primary"),
                phone_secondary=contact.get("phone_secondary"),
                company=contact.get("company"),
                designation=contact.get("designation"),
                address=contact.get("address"),
                city=contact.get("city"),
                pincode=contact.get("pincode"),
                website=contact.get("website"),
                source_file=os.path.basename(file_path),
                field_origin={k: "local" for k in FIELD_KEYS if contact.get(k)},
            )
            return ExtractionResult(contacts=[nc], adapter="eml", local_only=True)
        except Exception as e:
            return ExtractionResult(contacts=[], warnings=[str(e)], adapter="eml", local_only=True)


