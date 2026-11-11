# api/quality.py — data-quality rule catalogue actually enforced by the server.
# Derived from services/validation.py (field validators) and services/dedup.py
# (duplicate bands) — not a frontend-side list.
from fastapi import APIRouter

from services import validation
from services import dedup

router = APIRouter()


_FIELD_SEVERITY = {
    "email": "error",             # validate_email → INVALID
    "email_primary": "error",
    "email_secondary": "error",
    "phone_primary": "error",
    "phone_secondary": "warning",
    "whatsapp": "error",
    "pincode": "error",
    "name": "warning",
    "company": "error",           # validate_company → FIELD_MAPPING_ERROR
    "company_name": "error",
    "position": "error",
    "designation": "error",
    "industry": "error",
    "address": "warning",
    "city": "error",
    "website": "error",
}


def _field_rows() -> list[dict]:
    # One row per registered field validator — the catalogue the server runs.
    rows = []
    for field in sorted(validation._FIELD_VALIDATORS):
        severity = _FIELD_SEVERITY.get(field)
        if severity is None:
            severity = validation.SEVERITY.get("UNCERTAIN", "warning")
        rows.append({"field": field, "severity": severity, "status": "enabled"})
    return rows


@router.get("/dedup-rules")
async def list_dedup_rules():
    rows = _field_rows()
    rows += [
        {"field": "dedup: exact duplicate", "severity": "error", "status": "enabled"},
        {"field": "dedup: probable duplicate", "severity": "warning", "status": "enabled"},
        {"field": "dedup: conflict", "severity": "warning", "status": "enabled"},
        {"field": "dedup: unique", "severity": "info", "status": "enabled"},
    ]
    return {"rows": rows, "bands": {
        "exact_duplicate": dedup.EXACT_DUPLICATE,
        "probable_duplicate": dedup.PROBABLE_DUPLICATE,
        "conflict": dedup.CONFLICT,
        "unique": dedup.UNIQUE,
    }}
