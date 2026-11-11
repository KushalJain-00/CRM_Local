# services/adapters/xls.py — XLS extraction adapter
"""XLS → normalized contacts via the shared table mapper (parse.py / services/parser.py)."""
from . import ExtractionResult
from ._table import contacts_from_table


class XlsAdapter:
    name = "xls"

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".xls")

    async def extract(self, file_path: str) -> ExtractionResult:
        try:
            from services import parser as legacy
            with open(file_path, "rb") as f:
                table = legacy.parse_xls(f.read())
            return contacts_from_table(file_path, table, "xls")
        except Exception as e:
            return ExtractionResult(contacts=[], warnings=[str(e)], adapter="xls", local_only=True)
