# services/adapters/_table.py — shared table→contacts mapping for the
# tabular adapters (csv/xlsx/xls). One implementation, one header-mapping
# engine (parse.py); adapters only differ in file decoding.
import os

from . import NormalizedContact, ExtractionResult


def contacts_from_table(path: str, table: dict, adapter: str) -> ExtractionResult:
    from services import parse
    name = os.path.basename(path)
    warnings: list[str] = []
    contacts: list[NormalizedContact] = []
    skipped = 0
    # Multi-sheet workbooks have per-sheet schemas — map headers per sheet,
    # not against the union (sheet 2's "E-mail" must not be swallowed by
    # sheet 1's already-claimed "Email").
    groups: dict[str, list[dict]] = {}
    for row in table["rows"]:
        groups.setdefault(row.get("_sheet") or "", []).append(row)
    for sheet, rows in groups.items():
        # Union of keys across all rows of the sheet — fallback-built rows
        # may carry different keys (e.g. a later row has City/Pincode).
        sheet_headers = list(dict.fromkeys(
            k for row in rows for k in row if not str(k).startswith("_")))
        mapping, unmatched, confidence = parse.map_headers(sheet_headers)
        tag = f"[{sheet}] " if len(groups) > 1 else ""
        if unmatched:
            warnings.append(f"{tag}unrecognized columns ignored: {', '.join(unmatched[:6])}")
        if not (mapping.get("email_primary") or mapping.get("phone_primary")):
            warnings.append(f"{tag}no email or phone column recognized — sheet skipped")
            skipped += len(rows)
            continue
        if confidence < 0.4:
            warnings.append(f"{tag}header-mapping confidence {int(confidence * 100)}%")
        for row in rows:
            c = parse.row_to_contact(row, mapping)
            if not c:
                skipped += 1
                continue
            contacts.append(NormalizedContact(
                name=c.get("name"),
                email_primary=c.get("email_primary"),
                email_secondary=c.get("email_secondary"),
                phone_primary=c.get("phone_primary"),
                phone_secondary=c.get("phone_secondary"),
                company=c.get("company"),
                designation=c.get("designation"),
                address=c.get("address"),
                city=c.get("city"),
                pincode=c.get("pincode"),
                website=c.get("website"),
                source_file=name,
                source_row=row.get("_row"),
                source_sheet=sheet or None,
            ))
    if skipped:
        warnings.append(f"{skipped} row(s) skipped — no email or phone present")
    return ExtractionResult(contacts=contacts, warnings=warnings,
                            adapter=adapter, local_only=True, table=table)
