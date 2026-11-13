# services/adapters/csv.py — CSV extraction adapter
"""CSV → normalized contacts via the shared table mapper (parse.py)."""

from . import ExtractionResult
from ._table import contacts_from_table

class CsvAdapter:
    name = "csv"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".csv")

    async def extract(self, file_path: str) -> ExtractionResult:
        try:
            from services import parse
            with open(file_path, "rb") as f:
                table = parse.parse_csv(f.read())
            return contacts_from_table(file_path, table, "csv")
        except Exception as e:
            return ExtractionResult(contacts=[], warnings=[str(e)], adapter="csv", local_only=True)
