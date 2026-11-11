# services/adapters/__init__.py — Extraction adapter registry
"""Universal extraction adapter registry.

Adapters implement the ExtractionAdapter protocol and return ExtractionResult
containing a list of NormalizedContact records with provenance.
"""
from typing import Protocol, runtime_checkable, Optional
from dataclasses import dataclass, field
import os


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


@dataclass
class ExtractionResult:
    """Result from an extraction adapter."""
    contacts: list[NormalizedContact] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    adapter: str = ""
    local_only: bool = False


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