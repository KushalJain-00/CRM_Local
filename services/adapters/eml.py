# services/adapters/eml.py — EML extraction adapter
"""Wraps services/eml_processor.py for .eml files. Deterministic Layer-1 only;
the pipeline runs the contract-validated AI stage and the email-row link."""
import os

from . import ExtractionResult, eml_to_normalized

class EmlAdapter:
    name = "eml"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".eml")

    async def extract(self, file_path: str) -> ExtractionResult:
        from services.eml_processor import parse_eml_bytes, extract_local_fields, merge_fields
        try:
            with open(file_path, "rb") as f:
                raw = f.read()
            parsed = parse_eml_bytes(raw, os.path.basename(file_path))
            merged = merge_fields(extract_local_fields(parsed), None)
            nc = eml_to_normalized(
                merged, None, source_file=os.path.basename(file_path),
                to_emails=parsed.to_emails or None,
                cc_emails=parsed.cc_emails or None,
                bcc_emails=parsed.bcc_emails or None,
            )
            return ExtractionResult(contacts=[nc], adapter="eml",
                                    local_only=True, parsed=parsed)
        except Exception as e:
            return ExtractionResult(contacts=[], warnings=[str(e)],
                                    adapter="eml", local_only=True)
