"""Read explicitly labelled contact fields before relying on signature heuristics."""
import re

from services.eml_processor import ADDRESS_LINE_RE, extract_local_fields
from services.keys import EMAIL_RE, phone_key

_LABELS = {
    "name": "name|full name|contact name",
    "email": "e-?mail(?: address)?",
    "phone_primary": "phone(?: primary)?|primary phone|mobile|tel(?:ephone)?|contact number",
    "phone_secondary": "secondary phone|phone secondary|alternate phone|alt phone|office phone|landline",
    "company": "company(?: name)?|organisation|organization|employer",
    "designation": "designation|job title|title|position|role",
    "address": "address|office address|registered office|mailing address",
    "city": "city|town",
    "pincode": "pin(?:[ -]?code)?|postal code|post code|postcode|zip(?: code)?",
    "website": "website|web site|web|url",
}
_LABEL = re.compile(
    r"^\s*(?:" + "|".join(f"(?P<{field}>{labels})" for field, labels in _LABELS.items())
    + r")\s*:\s*(?P<value>.+?)\s*$", re.I,
)
_PHONE = re.compile(r"\+?[\d(][\d(). \t-]{5,}[\d)]")
_POSTAL = re.compile(r"(?:[\w -]{2,12})\Z")


def extract_contact_fields(parsed):
    fields = extract_local_fields(parsed)
    zone = parsed.signature_block or parsed.body_text
    explicit = {}
    evidence = {}
    warnings = []
    for line in zone.splitlines():
        match = _LABEL.match(line)
        if not match:
            continue
        field = next(field for field in _LABELS if match.group(field) is not None)
        value = match["value"]
        if field.startswith("phone_"):
            numbers = [item.group().strip() for item in _PHONE.finditer(value)]
            numbers = [number for number in numbers
                       if 7 <= len(re.sub(r"\D", "", number)) <= 15 and phone_key(number)]
            if not numbers:
                continue
            value = ", ".join(numbers)
        elif field == "email":
            address = EMAIL_RE.search(value)
            if not address:
                continue
            value = address.group().lower()
        elif field == "pincode" and (not _POSTAL.fullmatch(value) or not any(c.isdigit() for c in value)):
            continue
        explicit.setdefault(field, {}).setdefault(value, line.strip())

    # A labelled contact block in a message without a sign-off needs context.
    if not parsed.signature_block and len(explicit) < 2:
        explicit.clear()
    for field, values in explicit.items():
        if len(values) > 1:
            fields[field] = None
            warnings.append(f"Conflicting email values for {field.replace('_', ' ')}")
            continue
        value, line = next(iter(values.items()))
        fields[field] = value
        evidence[field] = {"excerpt": line, "location": "email contact block", "confidence": "high"}

    if "phone_primary" in explicit and fields["phone_primary"] and ", " in fields["phone_primary"]:
        first, rest = fields["phone_primary"].split(", ", 1)
        fields["phone_primary"] = first
        if "phone_secondary" not in explicit:
            fields["phone_secondary"] = rest
            evidence["phone_secondary"] = evidence["phone_primary"]
    if fields["phone_primary"] and fields["phone_secondary"]:
        primary = phone_key(fields["phone_primary"])
        secondary = [phone for phone in fields["phone_secondary"].split(", ")
                     if phone_key(phone) != primary]
        fields["phone_secondary"] = ", ".join(secondary) or None

    sender = EMAIL_RE.search(parsed.sender_email or "")
    if sender:
        fields["email"] = sender.group().lower()
        evidence["email"] = {"excerpt": sender.group(), "location": "From", "confidence": "high"}
    elif "email" not in explicit and not parsed.signature_block:
        fields["email"] = None

    if "pincode" not in explicit and fields["pincode"]:
        code = fields["pincode"]
        if not any(code in line and (ADDRESS_LINE_RE.search(line) or _LABEL.match(line)
                                      and _LABEL.match(line).group("address"))
                   for line in zone.splitlines()):
            # A standalone six-digit number may be an invoice or reference.
            fields["pincode"] = None

    if fields["name"] and _LABEL.match(fields["name"]):
        fields["name"] = parsed.sender_name or None
    return fields, {("email_primary" if key == "email" else key): item
                    for key, item in evidence.items() if fields[key]}, warnings
