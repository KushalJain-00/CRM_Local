# services/keys.py — THE identity-key implementation. Nothing else normalizes.
#
# Every stored identity key (email_key, phone_key, name_key, company_key,
# website_key) is produced here and only here, so rows written by intake,
# folder-scan, staging approval, and contact edit compare equal.
import re

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")

_HONORIFIC_RE = re.compile(r"^(?:mr|mrs|ms|dr|prof|shri|smt)\.?\s+")
_LEGAL_TOKENS = frozenset({
    "pvt", "private", "ltd", "limited", "llp", "inc", "corp", "corporation",
    "co", "company", "gmbh", "plc", "srl", "pte", "the",
})
_WS_RE = re.compile(r"\s+")


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def normalize_phone(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def phone_key(phone: str | None) -> str | None:
    """Digits-only with Indian variance collapsed: 12-digit 91 prefix and
    11-digit trunk 0 removed. None if fewer than 7 digits."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) >= 7 else None


def normalize_name(name: str | None) -> str:
    """Lowercase, strip, collapse whitespace. Plain comparison form used by
    is_duplicate — stored name_key goes through honorific stripping too."""
    return _WS_RE.sub(" ", (name or "").strip().lower())


def name_key(value) -> str | None:
    text = str(value if value is not None else "").strip().lower()
    text = _HONORIFIC_RE.sub("", text)
    text = re.sub(r"[.,'\"`\-]+", " ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text or None


def company_key(value) -> str | None:
    text = str(value if value is not None else "").strip().lower()
    text = re.sub(r"[.,'\"&]+", " ", text)
    tokens = [t for t in text.split() if t not in _LEGAL_TOKENS]
    return " ".join(tokens) or None


def website_key(value) -> str | None:
    text = str(value if value is not None else "").strip().lower()
    if not text:
        return None
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    text = text.split("/")[0].split("?")[0].split(":")[0].strip(". ")
    return text.strip(".") or None


def record_keys(d: dict) -> dict:
    return {
        "email_key": normalize_email(d.get("email_primary") or d.get("email")) or None,
        "phone_key": phone_key(d.get("phone_primary")),
        "name_key": name_key(d.get("name")),
        "company_key": company_key(d.get("company_name") or d.get("company")),
        "website_key": website_key(d.get("website")),
    }


def identity_key(d: dict) -> tuple:
    """Batch-identity tuple: email, else phone, else name+company. One record
    with all-NULL identity keys yields ("n", None, None) — callers treat that
    as 'no batch identity' and skip the batch-duplicate check."""
    keys = record_keys(d)
    if keys["email_key"]:
        return ("e", keys["email_key"])
    if keys["phone_key"]:
        return ("p", keys["phone_key"])
    return ("n", keys["name_key"], keys["company_key"])


def is_duplicate(email, phone, existing_emails: set[str], existing_phones: set[str],
                 name=None, existing_names: set[str] | None = None) -> str | None:
    """Return the reason string if duplicate, else None (email → phone → name)."""
    e = normalize_email(email)
    if e and e in existing_emails:
        return "email"
    p = normalize_phone(phone)
    if len(p) >= 10:
        # substring either way handles +91/landline variance
        for ep in existing_phones:
            if ep == p or (len(ep) >= 10 and (ep in p or p in ep)):
                return "phone"
    if name and existing_names:
        n = normalize_name(name)
        if n and len(n) >= 3 and n in existing_names:
            return "name"
    return None
