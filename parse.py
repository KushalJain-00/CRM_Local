# parse.py — turn a CRM file into rows, then map columns to contact fields.
import csv
import io
import re

import openpyxl

from services import parser as legacy

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")

CONTACT_FIELDS = [
    "name", "email_primary", "email_secondary", "phone_primary", "phone_secondary",
    "company", "designation", "address", "city", "pincode", "website",
]

# Longest/most specific aliases first so "email 2" never loses to "email".
ALIASES: dict[str, list[str]] = {
    "email_secondary": ["email 2", "email2", "alternate email", "secondary email",
                        "other email", "email alternate", "alt email", "e mail 2"],
    "phone_secondary": ["phone 2", "phone2", "mobile 2", "mobile2", "alternate phone",
                        "secondary phone", "other phone", "alt phone", "landline",
                        "telephone 2", "contact 2"],
    "email_primary": ["email", "e mail", "email id", "email address", "mail id", "mail",
                      "email1", "email 1"],
    "phone_primary": ["mobile", "phone", "phone no", "mobile no", "contact no",
                      "cell", "cellphone", "telephone", "tel", "whatsapp", "mobile number",
                      "phone number", "contact number"],
    "name": ["name", "full name", "contact name", "contact person", "person name",
             "customer name", "client name", "first name", "contact"],
    "company": ["company", "company name", "organization", "organisation", "firm",
                "account", "employer", "business"],
    "designation": ["designation", "job title", "title", "role", "position", "department"],
    "address": ["address", "full address", "office address", "location", "street"],
    "city": ["city", "town", "district"],
    "pincode": ["pincode", "pin code", "postal code", "zip code", "zip"],
    "website": ["website", "web site", "url", "web", "site"],
}


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (h or "").lower()).strip()


def map_headers(headers: list[str]) -> tuple[dict[str, str], list[str], float]:
    """Returns ({field: header}, unmatched_headers, confidence 0..1)."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for field, aliases in ALIASES.items():
        for alias in aliases:
            for h in headers:
                if h in used:
                    continue
                if _norm_header(h) == alias:
                    mapping[field] = h
                    used.add(h)
                    break
            if field in mapping:
                break
        if field in mapping:
            continue
        for alias in aliases:
            for h in headers:
                if h in used:
                    continue
                if alias in _norm_header(h):
                    mapping[field] = h
                    used.add(h)
                    break
            if field in mapping:
                break
    unmatched = [h for h in headers if h not in used]
    if not headers:
        return mapping, unmatched, 0.0
    # Confidence: how much of the useful surface we recognised, capped by
    # whether we found at least one identity column (email or phone).
    identity = bool(mapping.get("email_primary") or mapping.get("phone_primary"))
    confidence = len(mapping) / max(len(headers), 1)
    if not identity:
        confidence = min(confidence, 0.4)
    return mapping, unmatched, round(confidence, 2)


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_xlsx(content: bytes) -> dict:
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    headers: list[str] = []
    rows: list[dict] = []
    sheets_used: list[str] = []
    for ws in wb.worksheets:
        data = ws.iter_rows(values_only=True)
        first = next(data, None)
        if not first:
            continue
        sheet_headers = [f"Col_{i}" if not _cell(c) else _cell(c) for i, c in enumerate(first)]
        for sheet_row, raw in enumerate(data, start=2):
            row = {sheet_headers[i]: _cell(v) for i, v in enumerate(raw) if i < len(sheet_headers)}
            if any(row.values()):
                row["_row"] = sheet_row
                row["_sheet"] = ws.title
                rows.append(row)
                for h in sheet_headers:
                    if h not in headers:
                        headers.append(h)
        if rows:
            sheets_used.append(ws.title)
    wb.close()
    if not rows:
        raise ValueError("no data rows in workbook")
    return {"sheet": " + ".join(sheets_used), "headers": headers, "rows": rows}


def parse_csv(content: bytes) -> dict:
    text = content.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    first = next(reader, None)
    if not first:
        raise ValueError("empty csv")
    headers = [h.strip() or f"Col_{i}" for i, h in enumerate(first)]
    rows = []
    for raw in reader:
        row = {headers[i]: _cell(v) for i, v in enumerate(raw) if i < len(headers)}
        if any(row.values()):
            row["_row"] = reader.line_num
            row["_sheet"] = "CSV"
            rows.append(row)
    if not rows:
        raise ValueError("no data rows in csv")
    return {"sheet": "CSV", "headers": headers, "rows": rows}


def read_table(path: str) -> dict:
    """Dispatch on extension. Returns {sheet, headers, rows:[dict]}."""
    ext = path.rsplit(".", 1)[-1].lower()
    with open(path, "rb") as fh:
        content = fh.read()
    if ext == "xlsx":
        return parse_xlsx(content)
    if ext == "csv":
        return parse_csv(content)
    if ext == "xls":
        return legacy.parse_xls(content)
    if ext == "pdf":
        return legacy.parse_pdf(content)
    raise ValueError(f"unsupported file type: {ext}")


def clean_email(value: str) -> str:
    m = EMAIL_RE.search(value or "")
    return m.group(0).lower() if m else ""


def clean_phone(value: str) -> str:
    """Keep a readable phone string; reject anything with <7 digits."""
    raw = (value or "").strip()
    # Excel sometimes stores phones as 9.876543210e9
    if re.fullmatch(r"\d+(\.\d+)?e\+?\d+", raw, re.I):
        try:
            raw = str(int(float(raw)))
        except ValueError:
            pass
    digits = re.sub(r"\D", "", raw)
    return raw if len(digits) >= 7 else ""


def row_to_contact(row: dict, mapping: dict[str, str]) -> dict | None:
    """Apply the header mapping, normalise, and drop rows with no identity."""
    out = {f: None for f in CONTACT_FIELDS}
    for field, header in mapping.items():
        value = _cell(row.get(header))
        if not value:
            continue
        if field.startswith("email"):
            value = clean_email(value)
        elif field.startswith("phone"):
            value = clean_phone(value)
        out[field] = value or None
    if not out["email_primary"] and not out["phone_primary"]:
        return None
    return out
