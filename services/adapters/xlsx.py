# services/adapters/xlsx.py — XLSX extraction adapter
"""XLSX → normalized contacts via the shared table mapper (parse.py)."""
from . import ExtractionResult
from ._table import contacts_from_table


class XlsxAdapter:
    name = "xlsx"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".xlsx")

    async def extract(self, file_path: str) -> ExtractionResult:
        try:
            import parse
            with open(file_path, "rb") as f:
                table = parse.parse_xlsx(f.read())
            return contacts_from_table(file_path, table, "xlsx")
        except Exception as e:
            return ExtractionResult(contacts=[], warnings=[str(e)], adapter="xlsx", local_only=True)
