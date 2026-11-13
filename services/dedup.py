# services/dedup.py — band-comparison engine (spec §6/§8).
# Keys come from services/keys.py; this module only REPORTS match bands
# (EXACT/PROBABLE/CONFLICT/UNIQUE). It never decides a merge.
from difflib import SequenceMatcher

from services.keys import (  # re-exported for callers/tests of the public engine API
    normalize_email, normalize_phone, phone_key, name_key, company_key,
    website_key,
)

__all__ = [
    "EXACT_DUPLICATE", "PROBABLE_DUPLICATE", "UNIQUE", "CONFLICT",
    "normalize_email", "normalize_phone", "phone_key", "name_key",
    "company_key", "website_key", "email_key", "compare", "find_matches",
]

EXACT_DUPLICATE = "EXACT_DUPLICATE"
PROBABLE_DUPLICATE = "PROBABLE_DUPLICATE"
UNIQUE = "UNIQUE"
CONFLICT = "CONFLICT"

_FUZZY_THRESHOLD = 0.85


def email_key(value) -> str | None:
    return normalize_email(value) or None


def _email_of(record: dict) -> str | None:
    return email_key(record.get("email_primary") or record.get("email"))


def _phone_of(record: dict) -> str | None:
    return phone_key(record.get("phone_primary") or record.get("whatsapp"))


def _company_of(record: dict) -> str | None:
    return company_key(record.get("company_name") or record.get("company"))


def _phone_overlap(a: str, b: str) -> bool:
    return a == b or (len(a) >= 10 and len(b) >= 10 and (a in b or b in a))


def _similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    seq = SequenceMatcher(None, a, b).ratio()
    tokens_a, tokens_b = set(a.split()), set(b.split())
    jaccard = (len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
               if tokens_a and tokens_b else 0.0)
    return max(seq, jaccard)


def _result(band: str, score: float, matched_on: str, reasons: list[str]) -> dict:
    return {"band": band, "score": round(score, 2),
            "matched_on": matched_on, "reasons": reasons}


def compare(a: dict, b: dict) -> dict:
    """Report the match band between two contact-like records.

    Priority: exact email > exact phone (>=10 digits, containment) >
    name+company composite > name+company > fuzzy (human review only).
    CONFLICT = near-same identity with conflicting populated values.
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        return _result(UNIQUE, 0.0, "", ["not comparable"])
    ea, eb = _email_of(a), _email_of(b)
    pa, pb = _phone_of(a), _phone_of(b)
    na, nb = name_key(a.get("name")), name_key(b.get("name"))
    ca, cb = _company_of(a), _company_of(b)

    # 1. Exact email — conflicting names mean conflicting identities.
    if ea and eb and ea == eb:
        if na and nb and na != nb:
            return _result(CONFLICT, 1.0, "email",
                           ["same normalized email, different names"])
        return _result(EXACT_DUPLICATE, 1.0, "email", ["same normalized email"])

    # 2. Exact phone (>=10 digits, containment).
    if pa and pb and len(pa) >= 10 and len(pb) >= 10 and _phone_overlap(pa, pb):
        if na and nb and na != nb:
            return _result(CONFLICT, 1.0, "phone",
                           ["same phone, different names"])
        return _result(EXACT_DUPLICATE, 1.0, "phone", ["same normalized phone"])

    # 3. Strong composite / name+company.
    if na and nb and na == nb:
        if ca and cb and ca == cb:
            if ea and eb and ea != eb:
                return _result(CONFLICT, 0.95, "name+company",
                               ["same name and company, different emails"])
            if (pa and pb and len(pa) >= 10 and len(pb) >= 10
                    and not _phone_overlap(pa, pb)):
                return _result(CONFLICT, 0.95, "name+company",
                               ["same name and company, different phones"])
            return _result(PROBABLE_DUPLICATE, 0.9, "name+company",
                           ["same name and company — review before merging"])
        if ca and cb and ca != cb:
            # Same name, different company = different records; name alone
            # must never score as certain.
            return _result(UNIQUE, 0.0, "",
                           ["same name but different company — treated as different records"])
        # Company missing on at least one side: exact name alone is only a
        # review signal, never a certain match.
        return _result(PROBABLE_DUPLICATE, 0.6, "name",
                       ["name-only match without company/phone confirmation — human review"])

    # 4. Fuzzy tier — reserved for human review, never auto-certain.
    if na and nb and _similarity(na, nb) >= _FUZZY_THRESHOLD:
        if ca and cb and ca != cb:
            return _result(UNIQUE, 0.0, "",
                           ["similar names but different companies — different records"])
        if ea and eb and ea != eb:
            if ca and cb and ca == cb:
                return _result(CONFLICT, 0.9, "name+company",
                               ["similar name with matching company but different emails"])
            return _result(UNIQUE, 0.0, "",
                           ["similar names but different emails — different records"])
        if ca and cb and ca == cb:
            return _result(PROBABLE_DUPLICATE, 0.8, "name+company",
                           ["fuzzy name with same company — human review"])
        return _result(PROBABLE_DUPLICATE, 0.75, "fuzzy_name",
                       ["fuzzy name similarity — human review only"])

    return _result(UNIQUE, 0.0, "", ["no identity match"])


def find_matches(candidate: dict, records: list[dict]) -> list[dict]:
    """Report every non-UNIQUE comparison of candidate against records,
    best score first. Reports matches only — never decides a merge."""
    matches = []
    for index, record in enumerate(records):
        match = compare(candidate, record)
        if match["band"] != UNIQUE:
            matches.append({"index": index, **match})
    matches.sort(key=lambda m: (-m["score"], m["index"]))
    return matches
