# services/adapters/eml.py — EML extraction adapter
"""Wraps services/eml_processor.py for .eml files. Deterministic Layer-1 only;
the pipeline runs the contract-validated AI stage and the email-row link."""
import os

from . import ExtractionResult, eml_to_normalized
from services.eml_fields import extract_contact_fields

class EmlAdapter:
    name = "eml"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".eml")

    async def extract(self, file_path: str) -> ExtractionResult:
        from services.eml_processor import parse_eml_bytes
        try:
            with open(file_path, "rb") as f:
                raw = f.read()
            parsed = parse_eml_bytes(raw, os.path.basename(file_path))
            merged, evidence, warnings = extract_contact_fields(parsed)
            nc = eml_to_normalized(
                merged, None, source_file=os.path.basename(file_path),
                to_emails=parsed.to_emails or None,
                cc_emails=parsed.cc_emails or None,
                bcc_emails=parsed.bcc_emails or None,
            )
            nc.field_evidence = evidence
            return ExtractionResult(contacts=[nc], adapter="eml", warnings=warnings,
                                    local_only=True, parsed=parsed)
        except Exception as e:
            return ExtractionResult(contacts=[], warnings=[str(e)], error=str(e),
                                    adapter="eml", local_only=True)
