import io

import openpyxl

import export


def test_export_writes_styled_sheet_with_headers():
    rows = [{
        "name": "Asha Rao", "email_primary": "asha@example.com",
        "phone_primary": "9876543210", "company": "Acme",
        "source_file": "contacts.xlsx",
    }]
    data = export.contacts_to_xlsx(rows, "CRM Contacts")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.active
    assert ws.title == "CRM Contacts"
    headers = [c.value for c in ws[1]]
    assert headers[:3] == ["Name", "Email", "Alt Email"]
    assert ws["A2"].value == "Asha Rao"
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref == "A1:L2"


def test_export_handles_empty_rows():
    data = export.contacts_to_xlsx([], "EML Contacts")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert wb.active.max_row == 1
