# services/validation.py
"""Unified post-extraction field validator (spec §7, field matrix §5.1).

One validator for every source type and both extraction layers. It only
reports issues — it NEVER mutates or deletes the raw value it inspects;
flagged values stay in the record and in raw_source_data.
"""
import re

from services.keys import normalize_email, phone_key

# Exact issue categories (spec §5.2 / brief §7).
SEVERITY = {
    "INVALID": "error",
    "SUSPICIOUS": "warning",
    "MISSING": "error",
    "UNCERTAIN": "warning",
    "FIELD_MAPPING_ERROR": "error",
    "POSSIBLE_DUPLICATE": "info",
    "CONFLICT": "warning",
}
ISSUE_CATEGORIES = tuple(SEVERITY.keys())

_EMAIL_FULL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_FILE_EXT_RE = re.compile(
    r"\.(?:png|jpe?g|gif|bmp|tiff?|pdf|docx?|xlsx?|pptx?|eml|msg|zip|csv|txt)$", re.I)
_IMAGE_LOCAL_RE = re.compile(
    r"^(?:image|img|picture|photo|screenshot|attachment)[\w.-]*$", re.I)
_HEX_DOMAIN_RE = re.compile(r"^[0-9a-fA-F]{6,}\.[A-Za-z]{2,4}$")

# H4 — sentence-as-name heuristics.
_SENTENCE_STARTERS = (
    "share ", "please ", "kindly ", "dear ", "hi ", "hello ", "thanks ",
    "thank ", "regards ", "let ", "we ", "i ", "send ", "find ", "attach ",
)
# H5 — technical-spec-as-company heuristics (digit + unit, spec-sheet style).
_SPEC_RE = re.compile(
    r"\d+\s*(?:ft|feet|mm|cm|inch|in|kg|psi|bps|inc)\b|size\s*[:.\-]", re.I)
_ROLE_TITLE_START_RE = re.compile(
    r"^(?:(?:mr|mrs|ms|dr|prof|shri|smt)\.?\s+)?(?:senior\s+|junior\s+|chief\s+)?"
    r"(?:manager|director|executive|president|head|ceo|cto|cfo|coordinator|officer|"
    r"analyst|consultant|supervisor|owner|proprietor|founder|accountant|architect|"
    r"technician|sales)\b", re.I)
_COMPANY_SUFFIX_RE = re.compile(
    r"\b(?:pvt|ltd|limited|llp|inc|corp|corporation|co|gmbh|plc)\b", re.I)
# H1 — role words must never sit in industry; industry words never in position.
_ROLE_RE = re.compile(
    r"\b(?:manager|director|engineer|executive|president|head|associate|founder|"
    r"sales|ceo|cto|cfo|coordinator|officer|analyst|consultant|lead|supervisor|"
    r"owner|proprietor|accountant)\b", re.I)
_INDUSTRY_RE = re.compile(
    r"\b(?:manufactur|industr|textile|engineer|chemical|trading|export|import|"
    r"retail|construct|agricultur|logistic|pharmaceut|software|steel|plastic|"
    r"packaging|automobil|automotive|mining|cement|printing|jewell|electronic)\w*",
    re.I)
# H6 — labels that legitimately sit beside a phone number; anything else
# spelled out next to digits is a possible ID/reference number.
_PHONE_LABEL_RE = re.compile(
    r"^(?:whatsapp|wa|mobile|mob|phone|ph|tel|cell|contact|no|num|number|std|"
    r"landline|telephone|call|fax|office|home|work|res|direct|ext|extension)$",
    re.I)
_WHATSAPP_RE = re.compile(r"\bwhatsapp\b|\bwa\b|wa:", re.I)

# Explicit international prefixes only — a country code is never invented.
_CC_MAP = {
    91: "IN", 1: "US", 44: "UK", 971: "AE", 65: "SG", 61: "AU", 81: "JP",
    49: "DE", 86: "CN", 92: "PK", 880: "BD", 94: "LK", 977: "NP",
    33: "FR", 7: "RU", 55: "BR", 27: "ZA", 82: "KR", 64: "NZ", 353: "IE",
    60: "MY", 62: "ID", 63: "PH", 66: "TH", 90: "TR", 972: "IL", 20: "EG",
    234: "NG", 254: "KE", 233: "GH", 212: "MA", 255: "TZ", 256: "UG",
    260: "ZM", 263: "ZW",
}


def _issue(category: str, field: str, value, message: str) -> dict:
    return {"category": category, "field": field, "value": value,
            "message": message, "severity": SEVERITY[category]}


def _as_text(value) -> str:
    return value if isinstance(value, str) else str(value if value is not None else "")


# ---------------------------------------------------------------- email ----
def validate_email(value, field: str = "email_primary") -> list[dict]:
    text = _as_text(value).strip()
    if not text:
        return []
    if not _EMAIL_FULL_RE.match(text):
        return [_issue("INVALID", field, value,
                       "not a syntactically valid email address")]
    local, _, domain = text.rpartition("@")
    if _FILE_EXT_RE.search(local):
        return [_issue("SUSPICIOUS", field, value,
                       "local part looks like a filename artefact (embedded image/email file name)")]
    if _IMAGE_LOCAL_RE.match(local) and "." in local:
        return [_issue("SUSPICIOUS", field, value,
                       "local part looks like an embedded image name")]
    if _HEX_DOMAIN_RE.match(domain):
        return [_issue("SUSPICIOUS", field, value,
                       "domain is a hex-blob pattern typical of embedded image artefacts")]
    return []  # unfamiliar-but-well-formed domains are never rejected (H8)


# ---------------------------------------------------------------- phone ----
def _match_cc(digits: str) -> str | None:
    for length in (3, 2, 1):
        if len(digits) >= length:
            code = int(digits[:length])
            if code in _CC_MAP:
                return _CC_MAP[code]
    return None


def detect_phone_country(value) -> str | None:
    """Country from an explicit +cc / 00cc prefix only — never invented."""
    match = re.match(r"^(?:\+|00)(\d{1,3})", _as_text(value).strip())
    if not match:
        return None
    return _match_cc(match.group(1))


def classify_phone(value) -> str:
    """mobile | landline | std | whatsapp | international | unknown."""
    text = _as_text(value).strip()
    if not text:
        return "unknown"
    if _WHATSAPP_RE.search(text):
        return "whatsapp"
    if re.search(r"\bstd\b", text, re.I):
        return "std"
    key = phone_key(text)
    if not key:
        return "unknown"
    prefix = re.match(r"^(?:\+|00)(\d{1,3})", text)
    if prefix:
        country = _match_cc(prefix.group(1))
        if country != "IN":
            return "international"  # explicit non-IN prefix
        # +91 falls through to Indian classification
    if len(key) == 10:
        if key[0] in "6789":
            return "mobile"
        if key[0] in "2345":
            return "landline"
    return "unknown"


def _stray_letters(text: str) -> bool:
    for token in re.split(r"[\s:;,\-().]+", text):
        if token and re.search(r"[A-Za-z]", token) and not _PHONE_LABEL_RE.match(token):
            return True
    return False


def validate_phone(value, field: str = "phone_primary") -> list[dict]:
    text = _as_text(value).strip()
    if not text:
        return []
    key = phone_key(text)
    if key is None or len(key) < 7:
        return [_issue("INVALID", field, value, "fewer than 7 digits — not a phone number")]
    if _stray_letters(text):
        return [_issue("UNCERTAIN", field, value,
                       "digits next to unrecognised text — possible ID/reference number, not a phone")]
    if len(key) in (7, 8, 9):
        return [_issue("UNCERTAIN", field, value,
                       "ambiguous digit length — could be a landline/extension without STD code")]
    return []  # mobile/landline/STD/intl with explicit prefix all pass


# -------------------------------------------------------------- pincode ----
def validate_pincode(value, field: str = "pincode") -> list[dict]:
    text = _as_text(value).strip()
    if not text:
        return []
    if re.fullmatch(r"\d{6}", text):
        if text[0] == "0":
            return [_issue("SUSPICIOUS", field, value,
                           "6 digits starting with 0 is not an Indian PIN format")]
        return []  # valid Indian PIN
    if text.isdigit():
        if 5 <= len(text) <= 9:
            return []  # plausible international ZIP — never rejected for being non-IN
        return [_issue("INVALID", field, value, "not a postal code shape")]
    compact = text.replace(" ", "").upper()
    if 5 <= len(compact) <= 8 and re.search(r"\d", compact) and re.search(r"[A-Z]", compact):
        return []  # well-formed alphanumeric international postcode (e.g. SW1A 1AA)
    if re.fullmatch(r"[A-Za-z]\d[A-Za-z]\s?\d[A-Za-z]\d", text):
        return []
    return [_issue("INVALID", field, value, "not a postal code shape")]


# ----------------------------------------------------------------- name ----
def validate_name(value, field: str = "name") -> list[dict]:
    text = _as_text(value).strip()
    if not text:
        return []
    tokens = text.split()
    if "@" in text:
        return [_issue("SUSPICIOUS", field, value, "looks like an email address, not a name")]
    if text[-1] in ".!?" and len(tokens) >= 4:
        return [_issue("SUSPICIOUS", field, value,
                       "sentence-as-name: sentence-shaped value in a name field")]
    if len(tokens) >= 7:
        return [_issue("SUSPICIOUS", field, value,
                       "too many tokens to be a person name — likely prose")]
    if text.lower().startswith(_SENTENCE_STARTERS):
        return [_issue("SUSPICIOUS", field, value,
                       "sentence starter in a name field — likely a sentence, not a name")]
    if len(text) > 80:
        return [_issue("SUSPICIOUS", field, value, "longer than 80 chars — not a person name")]
    return []


# -------------------------------------------------------------- company ----
def validate_company(value, field: str = "company_name") -> list[dict]:
    text = _as_text(value).strip()
    if not text:
        return []
    if (_ROLE_TITLE_START_RE.match(text)
            and not _COMPANY_SUFFIX_RE.search(text)):
        return [_issue("FIELD_MAPPING_ERROR", field, value,
                       "role title mapped into the company field")]
    if _SPEC_RE.search(text) or text.count(".-") >= 2:
        return [_issue("SUSPICIOUS", field, value,
                       "technical specification text in the company name field "
                       "(value preserved; check column mapping)")]
    return []


# ----------------------------------------------------------- designation ---
def validate_position(value, field: str = "position") -> list[dict]:
    text = _as_text(value).strip()
    if not text:
        return []
    if "@" in text:
        return [_issue("FIELD_MAPPING_ERROR", field, value,
                       "email address mapped into the designation field")]
    if _INDUSTRY_RE.search(text) and not _ROLE_RE.search(text):
        return [_issue("FIELD_MAPPING_ERROR", field, value,
                       "industry value mapped into the designation field (H1)")]
    return []


def validate_industry(value, field: str = "industry") -> list[dict]:
    text = _as_text(value).strip()
    if not text:
        return []
    if _ROLE_RE.search(text):
        return [_issue("FIELD_MAPPING_ERROR", field, value,
                       "designation/role value mapped into the industry field (H1)")]
    return []


# ------------------------------------------------------- address/city ------
def validate_address(value, field: str = "address") -> list[dict]:
    text = _as_text(value).strip()
    if not text:
        return []
    if "@" in text:
        return [_issue("FIELD_MAPPING_ERROR", field, value,
                       "email address mapped into the address field")]
    digits = re.sub(r"\D", "", text)
    if re.fullmatch(r"[\d\s\-()+.]+", text) and len(digits) >= 7:
        return [_issue("INVALID", field, value,
                       "phone/number-shaped value in the address field")]
    if len(text) > 500:
        return [_issue("SUSPICIOUS", field, value, "address longer than 500 chars")]
    return []  # unfamiliar international addresses pass untouched


def validate_city(value, field: str = "city") -> list[dict]:
    text = _as_text(value).strip()
    if not text:
        return []
    if re.fullmatch(r"\d+", text):
        return [_issue("INVALID", field, value, "digits only — not a city name")]
    if len(text) > 60:
        return [_issue("FIELD_MAPPING_ERROR", field, value,
                       "address-like value mapped into the city field")]
    return []


# -------------------------------------------------------------- website ----
def validate_website(value, field: str = "website") -> list[dict]:
    text = _as_text(value).strip()
    if not text:
        return []
    if "@" in text:
        return [_issue("FIELD_MAPPING_ERROR", field, value,
                       "email address mapped into the website field")]
    host = re.sub(r"^https?://", "", text, flags=re.I)
    host = re.sub(r"^www\.", "", host, flags=re.I).split("/")[0].strip(".").lower()
    if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host):
        return [_issue("INVALID", field, value, "not a domain-shaped website value")]
    if _FILE_EXT_RE.search(host):
        return [_issue("SUSPICIOUS", field, value, "filename artefact in the website field")]
    return []


# --------------------------------------------------------------- record ----
_FIELD_VALIDATORS = {
    "name": validate_name,
    "email": validate_email,
    "email_primary": validate_email,
    "email_secondary": validate_email,
    "phone_primary": validate_phone,
    "phone_secondary": validate_phone,
    "whatsapp": validate_phone,
    "pincode": validate_pincode,
    "company": validate_company,
    "company_name": validate_company,
    "position": validate_position,
    "designation": validate_position,
    "industry": validate_industry,
    "address": validate_address,
    "city": validate_city,
    "website": validate_website,
}


def validate_record(fields: dict, *, record_type: str = "contact") -> list[dict]:
    """Validate every recognised field plus record-level identity rules.

    record_type="contact" adds the MISSING / POSSIBLE_DUPLICATE / CONFLICT
    identity checks; pass record_type="company" for company-shaped records.
    Returns issue dicts; the input dict is never modified.
    """
    if not isinstance(fields, dict):
        return []
    issues: list[dict] = []
    for key, value in fields.items():
        validator = _FIELD_VALIDATORS.get(key)
        if validator is None or value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        issues.extend(validator(value, field=key))
    if record_type == "contact":
        issues.extend(_identity_issues(fields))
    return issues


def _identity_issues(fields: dict) -> list[dict]:
    issues: list[dict] = []
    has_email = bool(normalize_email(fields.get("email_primary"))
                     or normalize_email(fields.get("email_secondary"))
                     or normalize_email(fields.get("email")))
    has_phone = bool(fields.get("phone_primary") or fields.get("phone_secondary")
                     or fields.get("whatsapp"))
    if not has_email and not has_phone:
        issues.append(_issue("MISSING", "record", fields.get("name"),
                             "no email and no phone — record is not stageable as a contact"))

    primary = normalize_email(fields.get("email_primary"))
    secondary = normalize_email(fields.get("email_secondary"))
    if primary and secondary and primary == secondary:
        issues.append(_issue("POSSIBLE_DUPLICATE", "email_secondary",
                             fields.get("email_secondary"),
                             "secondary email equals the primary email"))
    p_primary = phone_key(fields.get("phone_primary"))
    p_secondary = phone_key(fields.get("phone_secondary"))
    if p_primary and p_secondary and p_primary == p_secondary:
        issues.append(_issue("POSSIBLE_DUPLICATE", "phone_secondary",
                             fields.get("phone_secondary"),
                             "secondary phone equals the primary phone"))

    country = _as_text(fields.get("phone_country")).strip().upper()
    raw = fields.get("phone_primary") or fields.get("whatsapp")
    if country and raw:
        derived = detect_phone_country(raw)
        if derived and derived != country:
            issues.append(_issue("CONFLICT", "phone_country",
                                 fields.get("phone_country"),
                                 f"phone_country '{country}' contradicts the explicit "
                                 f"prefix of the number (→ {derived})"))
        elif not derived:
            key = phone_key(raw)
            if key and len(key) == 10 and key[0] in "6789" and country != "IN":
                issues.append(_issue("CONFLICT", "phone_country",
                                     fields.get("phone_country"),
                                     f"phone_country '{country}' contradicts an "
                                     "Indian mobile-shaped number"))
    return issues
