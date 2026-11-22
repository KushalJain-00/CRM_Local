# export.py — build an .xlsx in memory from contact rows.
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

EMAIL_SOURCE_COLUMNS = [
    ("crm_contact_id", "CRM Contact ID"), ("staged_contact_id", "Staged Contact ID"),
    ("source_email_id", "Source Email ID"), ("source_file", "Source File"),
    ("dedup_status", "Dedup Status"), ("pushed_to_crm", "Pushed to CRM"),
    ("created_at", "Created At"), ("to_emails", "To"), ("cc_emails", "Cc"),
    ("bcc_emails", "Bcc"), ("source_secondary_phones", "Secondary Phones from Source"),
]

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


def contacts_to_xlsx(rows: list[dict], sheet_title: str = "Contacts", *,
                     email_sources: list[dict] | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title[:31]
    columns = COLUMNS if email_sources is None else [
        ("id", "ID"), *COLUMNS, ("created_at", "Created At"),
    ]
    _write_sheet(ws, rows, columns)
    if email_sources:
        _write_sheet(wb.create_sheet("Email sources"), email_sources, EMAIL_SOURCE_COLUMNS)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_sheet(ws, rows, columns):
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="2563EB")
    for col, (_, label) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")

    def _sanitize(val):
        if isinstance(val, str) and val and val[0] in ("=", "+", "-", "@"):
            return "'" + val
        return val

    for r, row in enumerate(rows, start=2):
        for c, (field, _) in enumerate(columns, start=1):
            ws.cell(row=r, column=c, value=_sanitize(row.get(field) if row.get(field) is not None else ""))

    for col, (field, label) in enumerate(columns, start=1):
        lengths = [len(label)] + [len(str(row.get(field) or "")) for row in rows[:200]]
        ws.column_dimensions[get_column_letter(col)].width = min(48, max(10, max(lengths) + 2))

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(1, len(rows) + 1)}"
