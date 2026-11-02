import openpyxl

import parse


def test_csv_parses_and_maps_columns():
    table = parse.parse_csv(
        b"Full Name,Email ID,Mobile No,Company Name,Designation,City\n"
        b"Asha Rao,asha@example.com,9876543210,Acme Pvt Ltd,Director,Pune\n"
    )
    mapping, unmatched, confidence = parse.map_headers(table["headers"])
    assert mapping["name"] == "Full Name"
    assert mapping["email_primary"] == "Email ID"
    assert mapping["phone_primary"] == "Mobile No"
    assert mapping["company"] == "Company Name"
    assert mapping["designation"] == "Designation"
    assert mapping["city"] == "City"
    assert unmatched == []
    assert confidence == 1.0

    contact = parse.row_to_contact(table["rows"][0], mapping)
    assert contact["email_primary"] == "asha@example.com"
    assert contact["phone_primary"] == "9876543210"
    assert contact["name"] == "Asha Rao"


def test_secondary_columns_win_over_primary_aliases():
    mapping, _, _ = parse.map_headers(["Email", "Email 2", "Phone", "Mobile 2"])
    assert mapping["email_primary"] == "Email"
    assert mapping["email_secondary"] == "Email 2"
    assert mapping["phone_primary"] == "Phone"
    assert mapping["phone_secondary"] == "Mobile 2"


def test_row_without_email_or_phone_is_dropped():
    mapping, _, _ = parse.map_headers(["Name", "Company"])
    row = {"Name": "Nobody", "Company": "Nowhere"}
    assert parse.row_to_contact(row, mapping) is None


def test_xlsx_parses_numeric_cells():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "Email", "Phone"])
    ws.append(["Asha Rao", "asha@example.com", 9876543210])
    import io
    buf = io.BytesIO()
    wb.save(buf)

    table = parse.parse_xlsx(buf.getvalue())
    assert table["rows"][0]["Phone"] == "9876543210"
    mapping, _, _ = parse.map_headers(table["headers"])
    contact = parse.row_to_contact(table["rows"][0], mapping)
    assert contact["phone_primary"] == "9876543210"


def test_excel_float_phone_is_cleaned():
    assert parse.clean_phone("9.876543210e9") == "9876543210"
    assert parse.clean_phone("123") == ""


def test_low_confidence_when_no_identity_column():
    _, _, confidence = parse.map_headers(["Name", "Company", "Notes"])
    assert confidence <= 0.4
