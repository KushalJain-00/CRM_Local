# services/adapters/__init__.py — Extraction adapter registry
"""Universal extraction adapter registry.

Adapters implement the ExtractionAdapter protocol and return ExtractionResult
containing a list of NormalizedContact records with provenance.
"""
from typing import Protocol, runtime_checkable
from dataclasses import dataclass, field

@dataclass
class NormalizedContact:
    """Canonical normalized contact record (C-02)."""
    name: str | None = None
    email_primary: str | None = None
    email_secondary: str | None = None
    phone_primary: str | None = None
    phone_secondary: str | None = None
    company: str | None = None
    designation: str | None = None
    address: str | None = None
    city: str | None = None
    pincode: str | None = None
    website: str | None = None
    whatsapp: str | None = None
    files: str | None = None
    products_misc: str | None = None
    source_file: str | None = None
    source_row: int | None = None
    source_sheet: str | None = None
    extraction_run_id: int | None = None
    field_origin: dict | None = None
    confidence: float = 0.0
    to_emails: str | None = None
    cc_emails: str | None = None
    bcc_emails: str | None = None

@dataclass
class ExtractionResult:
    """Result from an extraction adapter."""
    contacts: list[NormalizedContact] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    adapter: str = ""
    local_only: bool = False
    # .eml adapters stash the parsed message here so the pipeline can link the
    # email row and build the LLM prompt without re-parsing the file.
    parsed: object | None = None

# crm-extraction.v1 / merged FIELD_KEYS → normalized-contact boundary.
# One table, one place; every producer of contacts flows through it.
_CONTACT_MAP = (
    ("name", "name"),
    ("email", "email_primary"),
    ("phone_primary", "phone_primary"),
    ("phone_secondary", "phone_secondary"),
    ("company", "company"),
    ("designation", "designation"),
    ("address", "address"),
    ("city", "city"),
    ("pincode", "pincode"),
    ("website", "website"),
)

_MAGIC = {
    "xls": [b"\xd0\xcf\x11\xe0", b"\x09\x08\x08\x00"],
    "pdf": [b"%PDF"],
}

def check_signature(file_path: str, ext: str) -> None:
    """Reject files whose bytes do not match the extension they claim.
    Raises ValueError; adapters call this before opening their parser."""
    with open(file_path, "rb") as fh:
        head = fh.read(16)
    if not any(head[:len(m)] == m for m in _MAGIC[ext]):
        raise ValueError(f"file content does not match .{ext} format")

_ORIGIN_KEYS = ("name", "email", "phone_primary", "company",
                "designation", "address", "city", "pincode", "website")

def origin_map(ai: dict | None, merged: dict) -> dict:
    return {k: ("ai" if (ai and ai.get(k)) else "local")
            for k in _ORIGIN_KEYS if merged.get(k)}

def eml_to_normalized(merged: dict, ai: dict | None, *, source_file: str,
                      to_emails: str | None = None,
                      cc_emails: str | None = None,
                      bcc_emails: str | None = None) -> NormalizedContact:
    """Local+AI merged FIELD_KEYS dict → internal contact (recipients preserved)."""
    nc = NormalizedContact(source_file=source_file, field_origin=origin_map(ai, merged))
    for merged_key, field_name in _CONTACT_MAP:
        setattr(nc, field_name, merged.get(merged_key))
    nc.to_emails = to_emails
    nc.cc_emails = cc_emails
    nc.bcc_emails = bcc_emails
    return nc

def contract_to_normalized(ac: dict, *, source_file: str) -> NormalizedContact:
    """assist_document output (already contract-validated) → internal contact."""
    return NormalizedContact(
        name=ac.get("name"),
        email_primary=ac.get("email_primary"),
        email_secondary=ac.get("email_secondary"),
        phone_primary=ac.get("phone_primary"),
        phone_secondary=ac.get("phone_secondary"),
        whatsapp=ac.get("whatsapp"),
        company=ac.get("company"),
        designation=ac.get("designation"),
        address=ac.get("address"),
        city=ac.get("city"),
        pincode=ac.get("pincode"),
        website=ac.get("website"),
        source_file=source_file,
        field_origin=ac.get("field_origin"),
        confidence=ac.get("confidence") or 0.3,
    )

@runtime_checkable
class ExtractionAdapter(Protocol):
    """Common extraction adapter interface."""
    def can_handle(self, file_path: str) -> bool: ...
    async def extract(self, file_path: str) -> ExtractionResult: ...

# Import all adapters to register them
from . import xls, pdf, csv, txt, xlsx, eml  # noqa: F401

_ADAPTERS = []

def _collect_adapters():
    """Collect all registered adapter instances."""
    global _ADAPTERS
    if _ADAPTERS:
        return _ADAPTERS
    from .xls import XlsAdapter
    from .pdf import PdfAdapter
    from .csv import CsvAdapter
    from .txt import TxtAdapter
    from .xlsx import XlsxAdapter
    from .eml import EmlAdapter
    _ADAPTERS = [XlsAdapter(), PdfAdapter(), CsvAdapter(), TxtAdapter(), XlsxAdapter(), EmlAdapter()]
    return _ADAPTERS

def get_adapter(file_path: str):
    """Return the first adapter that can handle the file, or None."""
    for adapter in _collect_adapters():
        if adapter.can_handle(file_path):
            return adapter
    return None

def dispatch(file_path: str) -> str:
    """Return the adapter name for a file path, or 'unknown'."""
    adapter = get_adapter(file_path)
    return adapter.name if adapter else "unknown"