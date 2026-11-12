# PDF parser regression corpus — synthetic, no real data.
# Generated at test time with reportlab; pdfplumber is the parser under test.
import io

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from services.parser import parse_pdf


def _pdf(pages: list[list[str]]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 10)
    for lines in pages:
        y = 800
        for line in lines:
            c.drawString(72, y, line)
            y -= 18
        c.showPage()
    c.save()
    return buf.getvalue()


def test_single_page_labeled_pairs_email_with_own_phone():
    raw = _pdf([[
        "Name: Divya Krishnan",
        "Email: divya@example.com  Phone: 9822233445",
        "Company: Theta Traders",
        "Name: Manish Verma",
        "Email: manish@example.net  Phone: 9822255667",
        "Company: Iota Ltd",
    ]])
    rows = parse_pdf(raw)["rows"]
    by_name = {r.get("Name"): r for r in rows}
    assert by_name["Divya Krishnan"]["Phone"] == "9822233445"
    assert by_name["Divya Krishnan"]["Email"] == "divya@example.com"
    assert by_name["Manish Verma"]["Phone"] == "9822255667"
    assert by_name["Manish Verma"]["Email"] == "manish@example.net"


def test_multipage_pdf_keeps_page_provenance_rows():
    raw = _pdf([
        ["Name: Anita Rao",
         "Email: anita@example.com  Phone: 9811100011"],
        ["Name: Bhavesh Shah",
         "Email: bhavesh@example.com  Phone: 9811100022"],
    ])
    rows = parse_pdf(raw)["rows"]
    emails = {r["Email"] for r in rows}
    assert emails == {"anita@example.com", "bhavesh@example.com"}


def test_unicode_text_survives():
    raw = _pdf([[
        "Name: Émilie Brontë",
        "Email: emilie@example.fr  Phone: 0601234567",
    ]])
    rows = parse_pdf(raw)["rows"]
    assert any("emilie@example.fr" in (r.get("Email") or "") for r in rows)


def test_table_with_ruling_lines_is_extracted_as_table():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 9)
    x0, y0, row_h, col_w = 50, 780, 20, 130
    headers = ["Name", "Email", "Phone"]
    data = [["Name", "Email", "Phone"],
            ["Divya Krishnan", "divya@example.com", "9822233445"],
            ["Manish Verma", "manish@example.net", "9822255667"]]
    # header row + ruling lines (header lives INSIDE the grid)
    for i, h in enumerate(headers):
        c.drawString(x0 + i * col_w + 2, y0 - 6, h)
    for r in range(len(data) + 1):
        c.line(x0, y0 - r * row_h, x0 + 3 * col_w, y0 - r * row_h)
    for i in range(4):
        c.line(x0 + i * col_w, y0 + row_h, x0 + i * col_w, y0 - len(data) * row_h)
    for r, row in enumerate(data[1:], start=1):
        for i, val in enumerate(row):
            c.drawString(x0 + i * col_w + 2, y0 - (r + 1) * row_h + 6, val)
    c.showPage()
    c.save()
    rows = parse_pdf(buf.getvalue())["rows"]
    emails = {r.get("Email") for r in rows}
    assert "divya@example.com" in emails
    assert "manish@example.net" in emails


def test_garbage_pdf_raises_value_error():
    with pytest.raises(ValueError):
        parse_pdf(b"%PDF-1.4 not really a pdf at all \x00\x01\x02")


def test_empty_pdf_raises_value_error():
    raw = _pdf([[]])  # one blank page
    with pytest.raises(ValueError):
        parse_pdf(raw)


def test_truncated_pdf_raises_value_error():
    raw = _pdf([["Name: Asha Rao", "Email: asha@example.com"]])
    with pytest.raises(ValueError):
        parse_pdf(raw[: len(raw) // 2])


def test_no_phone_pairing_bleeds_across_records():
    raw = _pdf([[
        "Name: Person One",
        "Email: one@example.com  Phone: 9000000001",
        "Name: Person Two",
        "Email: two@example.com  Phone: 9000000002",
    ]])
    rows = parse_pdf(raw)["rows"]
    by_name = {r.get("Name"): r for r in rows}
    assert by_name["Person One"]["Phone"] == "9000000001"
    assert by_name["Person Two"]["Phone"] == "9000000002"
