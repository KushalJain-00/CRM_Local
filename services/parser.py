import xlrd
import re
import time
import os
from services.keys import EMAIL_RE


def parse_xls(content: bytes) -> dict:
    """
    Parse ALL valid sheets in an XLS workbook and merge
    them into a single unified dataset.
    """
    start_time = time.time()
    wb = xlrd.open_workbook(file_contents=content)
    all_rows = []
    all_headers = []
    sheet_names_used = []
    timeout_sec = int(os.getenv("PARSER_TIMEOUT", 15))

    for name in wb.sheet_names():
        if time.time() - start_time > timeout_sec:
            raise TimeoutError(f"XLS processing exceeded {timeout_sec} seconds limit")
            
        # Skip lookup / index sheets
        lname = name.lower()
        if re.search(r"mob no|email id|phone list|mobile list|index|lookup", lname):
            continue

        sheet = wb.sheet_by_name(name)
        if sheet.nrows < 2 or sheet.ncols <= 2:
            continue

        # Map column index to header name, skipping blank headers
        header_map = {}
        for c in range(sheet.ncols):
            h = str(sheet.cell_value(0, c)).strip()
            if h:
                header_map[c] = h
                if h not in all_headers:
                    all_headers.append(h)

        for r in range(1, sheet.nrows):
            if time.time() - start_time > timeout_sec:
                raise TimeoutError(f"XLS processing exceeded {timeout_sec} seconds limit")
                
            row = {}
            for c, h in header_map.items():
                if c >= sheet.ncols:
                    break
                
                try:
                    cell = sheet.cell(r, c)
                    val = cell.value
                    if cell.ctype == xlrd.XL_CELL_NUMBER:
                        val = int(val) if val == int(val) else val
                    elif cell.ctype == xlrd.XL_CELL_DATE:
                        from xlrd import xldate_as_tuple
                        import datetime
                        t = xldate_as_tuple(val, wb.datemode)
                        val = str(datetime.date(*t[:3]))
                    else:
                        val = str(val).strip() if val else ""
                except Exception:
                    val = ""
                    
                row[h] = val if val != "" else None
            if any(v for v in row.values() if v is not None):
                row["_row"] = r + 1
                row["_sheet"] = name
                all_rows.append(row)
        sheet_names_used.append(name)

    if not all_rows:
        raise ValueError("No data found in any sheet")

    combined_name = " + ".join(sheet_names_used) if len(sheet_names_used) > 1 else sheet_names_used[0]
    return {"sheet": combined_name, "headers": all_headers, "rows": all_rows}




def _looks_like_header(row: list) -> bool:
    """True when a table's first row reads like labels, not contact data."""
    vals = [str(c or "").strip() for c in row]
    nonempty = [v for v in vals if v]
    if len(nonempty) < 2:
        return False
    joined = " ".join(nonempty)
    if EMAIL_RE.search(joined):
        return False
    digits = re.sub(r"\D", "", joined)
    if len(digits) >= 7:  # contains a phone-like number → data row
        return False
    return True


def parse_pdf(content: bytes) -> dict:
    start_time = time.time()
    rows = []
    headers = None
    max_pages = int(os.getenv("PDF_MAX_PAGES", 200))
    timeout_sec = int(os.getenv("PARSER_TIMEOUT", 30))
    all_text_pages = []

    # pdfplumber (MIT) — AGPL-safe PDF parsing. Text extraction via pdfminer.six;
    # tables detected by ruling lines / cell rects.
    import io as _io
    import pdfplumber
    try:
        doc = pdfplumber.open(_io.BytesIO(content))
    except Exception as e:
        raise ValueError(f"could not open PDF: {e}") from e
    for page_num, page in enumerate(doc.pages):
        if time.time() - start_time > timeout_sec:
            raise TimeoutError(f"PDF processing exceeded {timeout_sec} seconds limit")
        if page_num >= max_pages:
            break

        tables_found = page.find_tables()
        table_found = False
        for tab in tables_found:
            table = tab.extract()
            if not table:
                continue
            table = [r for r in table if r and any(c for c in r if c)]
            if not table:
                continue
            table_found = True
            if headers is None and len(table) > 1:
                raw_headers = [str(c).strip() if c else f"Col_{i}" for i, c in enumerate(table[0])]
                if _looks_like_header(raw_headers):
                    headers = _dedupe_headers(raw_headers)
                    data_rows = table[1:]
                else:
                    headers = [f"Col_{i}" for i in range(len(table[0]))]
                    data_rows = table
            else:
                if headers:
                    first_row_cleaned = [str(c).strip() if c else '' for c in table[0]]
                    header_cleaned = [h.strip() for h in headers]
                    data_rows = table[1:] if first_row_cleaned == header_cleaned else table
                else:
                    data_rows = table
            for raw_row in data_rows:
                if not any(c for c in raw_row if c):
                    continue
                if headers:
                    row = {headers[i]: str(raw_row[i]).strip() if i < len(raw_row) and raw_row[i] else None
                           for i in range(len(headers))}
                else:
                    row = {f"Col_{i}": str(v).strip() if v else None for i, v in enumerate(raw_row)}
                if any(v for v in row.values() if v):
                    rows.append(row)

        text = page.extract_text() or ""
        if text and not table_found:
            all_text_pages.append(text)

    doc.close()

    # If tables produced any rows, return them
    if rows:
        if headers is None:
            headers = list(rows[0].keys()) if rows else []
        return {"sheet": "PDF Import", "headers": headers, "rows": rows}

    # ── Fallback: Extract structured data from raw text ─────────────
    full_text = '\n'.join(all_text_pages)
    if not full_text.strip():
        if rows:
            headers = headers or list(rows[0].keys())
            return {"sheet": "PDF Import", "headers": headers, "rows": rows}
        raise ValueError("No tabular data or text could be extracted from PDF")

    rows = _extract_contacts_from_text(full_text)

    if not rows:
        raise ValueError("No structured contact data could be extracted from PDF")

    headers = list(rows[0].keys()) if rows else []
    return {"sheet": "PDF Import", "headers": headers, "rows": rows}


def _extract_contacts_from_text(text: str) -> list:
    """
    Extract structured contact records from free-form PDF text.
    Tries multiple strategies: regex extraction, block parsing, line splitting.
    """
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if not lines:
        return []

    # Regex patterns
    # Loose candidate; digit count (7–15) is the real validator downstream.
    phone_re = re.compile(r'(?:\+\d{1,3}[\s\-.()/]*)?(?:\(?\d[\s\-.()/]*){7,14}\d')
    intl_phone_re = re.compile(r'\+\d{1,3}[\s\-.()/]*\d[\d\s\-.()/]{5,13}\d')
    email_re = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
    url_re = re.compile(r'(?:https?://|www\.)[^\s,;]+', re.I)
    pincode_re = re.compile(r'\b[1-9]\d{5}\b')

    # Strategy 1: group lines into blocks separated by numbering or "Name:"
    # markers; fields inside a block then describe one person.
    blocks = []
    current_block = []
    for line in lines:
        is_boundary = (
            re.match(r'^\d{1,4}[\.\)\s]', line) and len(current_block) > 2
        ) or (
            re.match(r'^\s*(?:full\s+)?name\s*[:\-]', line, re.I) and current_block
        )
        if is_boundary and current_block:
            blocks.append('\n'.join(current_block))
            current_block = []
        current_block.append(line)

    if current_block:
        blocks.append('\n'.join(current_block))

    # If we got reasonable blocks, extract from each
    if len(blocks) >= 2:
        rows = []
        for block in blocks:
            row = _extract_fields_from_block(block, phone_re, intl_phone_re, email_re, url_re, pincode_re)
            # A block without any email and any phone is not a contact record.
            if row and (row.get('Email') or row.get('Phone')):
                rows.append(row)
        if rows:
            return rows

    # Strategy 2: line-by-line pairing — each line that carries an email or a
    # phone yields one record. Never index-pair unrelated lines: a wrong
    # number attached to the wrong person is worse than a missing one.
    rows = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        emails = email_re.findall(line)
        phones = [p for p in phone_re.findall(line) + intl_phone_re.findall(line)
                  if 7 <= len(re.sub(r"\D", "", p)) <= 15]
        if not emails and not phones:
            continue
        row = {}
        if phones:
            row['Phone'] = phones[0]
            if len(phones) > 1:
                row['Phone 2'] = phones[1]
        if emails:
            row['Email'] = emails[0]
            if len(emails) > 1:
                row['Email 2'] = emails[1]
        urls = url_re.findall(line)
        if urls:
            row['Website'] = urls[0]
        pincodes = pincode_re.findall(line)
        if pincodes:
            row['Pincode'] = pincodes[0]
        # Company-like tokens on the same line (Theta Traders, Iota Ltd…)
        comp_m = re.search(r'(?:Company|Org(?:anization)?|Firm)\s*[:\-]?\s*([^,;|]{2,80})', line, re.I)
        if comp_m:
            comp = re.split(r'\s{2,}|\s+(?:City|Pincode|Zip|Phone|Email|Name|Designation|Title)\b', comp_m.group(1))[0].strip()
            if comp:
                row['Company'] = comp
        name_m = re.search(r'Name\s*[:\-]?\s*([A-Za-z][A-Za-z.\'\- ]{1,60}?)(?:\s{2,}|\s+(?:Email|Phone|Company|Designation|Title|City)\b|\s*,|$)', line, re.I)
        if name_m:
            cand = name_m.group(1).strip()
            if cand and not email_re.search(cand):
                row['Name'] = cand
        if any(v for v in row.values() if v):
            rows.append(row)
    if rows:
        return rows

    return []


def _extract_fields_from_block(block: str, phone_re, intl_phone_re, email_re, url_re, pincode_re) -> dict:
    """Extract contact fields from a text block."""
    row = {}
    phones = phone_re.findall(block)
    intl_phones = intl_phone_re.findall(block)
    all_phones = phones + intl_phones
    emails = email_re.findall(block)
    urls = url_re.findall(block)
    pincodes = pincode_re.findall(block)

    if all_phones:
        row['Phone'] = all_phones[0]
        if len(all_phones) > 1:
            row['Phone 2'] = all_phones[1]
    if emails:
        row['Email'] = emails[0]
    if urls:
        row['Website'] = urls[0]
    if pincodes:
        row['Pincode'] = pincodes[0]

    lines = block.strip().split('\n')

    # Labeled lines win over heuristics. Split on double spaces — the common
    # one-line-per-field layout ("Name: X  Email: y@z  Phone: 123").
    _LABELED = {
        "Name": "Name", "Email": "Email", "Email 2": "Email 2",
        "Phone": "Phone", "Phone 2": "Phone 2", "Mobile": "Phone",
        "Company": "Company", "Designation": "Designation", "Title": "Designation",
        "Address": "Address", "City": "City", "Pincode": "Pincode", "Zip": "Pincode",
        "Website": "Website", "Industry": "Industry", "Department": "Department",
    }
    for ln in lines:
        # Field split: double spaces/semicolons, or any boundary before a
        # known label (pdfplumber collapses double spaces to one).
        parts = re.split(
            r"\s{2,}|;|(?=(?:Email|Phone|Mobile|Name|Company|Designation|Title|"
            r"Address|City|Pincode|Zip|Website|Industry|Department)\s*[:\-])", ln)
        for part in parts:
            m = re.match(r"^\s*([A-Za-z][A-Za-z0-9 ]{0,30})\s*[:\-]\s*(.+?)\s*$", part)
            if not m:
                continue
            key = _LABELED.get(m.group(1).strip().title())
            if not key:
                continue
            val = m.group(2).strip()
            if key == "City":
                val = re.sub(r"\s*\b\d{5,6}\b\s*$", "", val).strip()
            if val and not row.get(key):
                row[key] = val[:120]

    # Try to extract company/person name from first line (only when no
    # labeled Name bound it).
    if lines and not row.get('Name'):
        first_line = re.sub(r'^\d{1,4}[\.\)\s]+', '', lines[0]).strip()
        # If first line doesn't look like a phone/email, treat as name
        if first_line and not phone_re.search(first_line) and not email_re.search(first_line):
            # Check if it looks like a company
            comp_re = re.compile(r'\b(ltd|pvt|inc|corp|llp|llc|industries|solutions|technologies|systems|services|enterprises|group|associates)\b', re.I)
            if comp_re.search(first_line):
                row['Company'] = first_line[:120]
            else:
                row['Name'] = first_line[:80]

    # Look for address-like content
    addr_parts = []
    for line in lines[1:]:
        line_clean = line.strip()
        if not line_clean:
            continue
        # Skip lines that are just phones/emails
        if phone_re.fullmatch(line_clean) or email_re.fullmatch(line_clean):
            continue
        if url_re.fullmatch(line_clean):
            continue
        # If line has address keywords, add it
        if re.search(r'\b(road|street|nagar|plot|block|estate|phase|sector|area|dist|taluka|gujarat|maharashtra|delhi|mumbai|chennai|kolkata|bangalore|hyderabad|pune|ahmedabad|surat|vadodara|rajkot|gidc|industrial)\b', line_clean, re.I):
            addr_parts.append(line_clean)

    if addr_parts:
        row['Address'] = ', '.join(addr_parts)[:200]

    return row


def _dedupe_headers(headers: list) -> list:
    seen = {}
    result = []
    for h in headers:
        h = h or "Unnamed"
        if h in seen:
            seen[h] += 1
            result.append(f"{h}_{seen[h]}")
        else:
            seen[h] = 0
            result.append(h)
    return result
