# export.py — build an .xlsx in memory from contact rows.
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

COLUMNS = [
    ("name", "Name"),
    ("email_primary", "Email"),
    ("email_secondary", "Alt Email"),
    ("phone_primary", "Phone"),
    ("phone_secondary", "Alt Phone"),
    ("company", "Company"),
    ("designation", "Designation"),
    ("address", "Address"),
    ("city", "City"),
    ("pincode", "Pincode"),
    ("website", "Website"),
    ("source_file", "Source File"),
]


def contacts_to_xlsx(rows: list[dict], sheet_title: str = "Contacts") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title[:31]

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="2563EB")
    for col, (_, label) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")

    for r, row in enumerate(rows, start=2):
        for c, (field, _) in enumerate(COLUMNS, start=1):
            ws.cell(row=r, column=c, value=row.get(field) or "")

    for col, (field, label) in enumerate(COLUMNS, start=1):
        lengths = [len(label)] + [len(str(row.get(field) or "")) for row in rows[:200]]
        ws.column_dimensions[get_column_letter(col)].width = min(48, max(10, max(lengths) + 2))

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{max(1, len(rows) + 1)}"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
