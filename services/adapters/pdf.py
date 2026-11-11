# services/adapters/pdf.py — PDF extraction adapter
"""PDF → text/tables via services/parser.py, mapped by the shared table mapper."""
from . import ExtractionResult
from ._table import contacts_from_table


class PdfAdapter:
    name = "pdf"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".pdf")

    async def extract(self, file_path: str) -> ExtractionResult:
        try:
            from services.parser import parse_pdf
            with open(file_path, "rb") as f:
                table = parse_pdf(f.read())
            return contacts_from_table(file_path, table, "pdf")
        except Exception as e:
            return ExtractionResult(contacts=[], warnings=[str(e)], adapter="pdf", local_only=True)
