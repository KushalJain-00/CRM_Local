# services/contract.py
"""crm-extraction.v1 contract gate — invalid AI output never reaches staging.

validate_extraction_result(payload, source_type) returns either
(validated_payload, []) or (None, issues) — whole-payload acceptance only,
never a partial strip-down (spec §3.2, §3.3 rejection path).
"""
import copy

from services.prompts.contact_extraction import EXTRACTION_CONTRACT

SCHEMA_VERSION = EXTRACTION_CONTRACT["schema_version"]

TOP_LEVEL_KEYS = tuple(EXTRACTION_CONTRACT.keys())
CONTACT_DEFAULTS = EXTRACTION_CONTRACT["contacts"][0]
COMPANY_DEFAULTS = EXTRACTION_CONTRACT["companies"][0]
EMAIL_DEFAULTS = EXTRACTION_CONTRACT["emails"][0]
CONTACT_KEYS = tuple(CONTACT_DEFAULTS.keys())
COMPANY_KEYS = tuple(COMPANY_DEFAULTS.keys())
EMAIL_KEYS = tuple(EMAIL_DEFAULTS.keys())
CONTACT_SCALAR_KEYS = tuple(k for k in CONTACT_KEYS if k not in ("confidence", "field_evidence"))
COMPANY_SCALAR_KEYS = tuple(k for k in COMPANY_KEYS if k not in ("confidence", "field_evidence"))
EMAIL_SCALAR_KEYS = tuple(k for k in EMAIL_KEYS
                          if k not in ("to_emails", "cc_emails", "bcc_emails",
                                       "contact_indices", "has_signature"))
EMAIL_LIST_KEYS = ("to_emails", "cc_emails", "bcc_emails", "contact_indices")
EVIDENCE_KEYS = ("excerpt", "location", "confidence")
CONFIDENCE_LEVELS = ("high", "medium", "low")
CALL_LOG_KEYS = ("contact_name", "company_name", "call_date", "duration_minutes",
                 "call_type", "outcome", "notes", "next_action", "next_action_date")
LIST_KEYS = ("companies", "contacts", "emails", "call_logs", "unmapped_fields", "warnings")

# Keys the LLM must never emit: DB identity / timestamps / session state (§6).
BANNED_DB_KEYS = frozenset({
    "id", "uuid", "created_at", "updated_at", "crm_contact_id", "contact_id",
    "company_id", "source_email_id", "session_id", "extraction_run_id",
    "user_id", "processed_at", "pushed_to_crm", "dedup_status", "created_by",
    "file_path", "email_key", "phone_key", "row_id", "record_id",
})


def _issue(code: str, path: str, message: str) -> dict:
    return {"code": code, "path": path, "message": message}


def _scan_banned(obj, path: str, issues: list) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in BANNED_DB_KEYS:
                issues.append(_issue(
                    "llm_emitted_db_field", f"{path}.{key}",
                    f"LLM must never emit '{key}' — DB identity/timestamps are backend-owned"))
            _scan_banned(value, f"{path}.{key}", issues)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _scan_banned(value, f"{path}[{i}]", issues)


def _check_keys(entry: dict, allowed: tuple, path: str, issues: list) -> None:
    for key in entry:
        if key in allowed:
            continue
        if key in BANNED_DB_KEYS:
            continue  # already reported by _scan_banned with a specific code
        if key == "contact_indices":
            issues.append(_issue(
                "contact_indices_scope", f"{path}.contact_indices",
                "contact_indices is only valid inside emails[] (D-021)"))
            continue
        issues.append(_issue("unexpected_key", f"{path}.{key}",
                             "unsupported key — the contract forbids extra keys"))


def _normalize_scalar(entry: dict, key: str, path: str, issues: list) -> None:
    value = entry[key]
    if value is None:
        return
    if not isinstance(value, str):
        issues.append(_issue("type_error", f"{path}.{key}",
                             f"expected string or null, got {type(value).__name__}"))
        return
    stripped = value.strip()
    if not stripped or stripped.lower() in ("null", "none"):
        entry[key] = None
    else:
        entry[key] = stripped


def _check_evidence(entry: dict, scalar_keys: tuple, path: str, issues: list) -> None:
    evidence = entry["field_evidence"]
    if not isinstance(evidence, dict):
        issues.append(_issue("type_error", f"{path}.field_evidence",
                             "field_evidence must be an object"))
        return
    for key, item in evidence.items():
        if key not in scalar_keys:
            issues.append(_issue("invalid_field_evidence", f"{path}.field_evidence.{key}",
                                 "evidence key does not correspond to a contract field"))
            continue
        item_path = f"{path}.field_evidence.{key}"
        if not isinstance(item, dict):
            issues.append(_issue("type_error", item_path, "evidence must be an object"))
            continue
        extra = [k for k in item if k not in EVIDENCE_KEYS]
        if extra:
            issues.append(_issue("invalid_field_evidence", f"{item_path}.{extra[0]}",
                                 "unsupported evidence key"))
        excerpt = item.get("excerpt")
        if not isinstance(excerpt, str) or not excerpt.strip():
            issues.append(_issue("invalid_field_evidence", f"{item_path}.excerpt",
                                 "excerpt must be a non-empty string"))
        location = item.get("location")
        if location is not None and not isinstance(location, str):
            issues.append(_issue("type_error", f"{item_path}.location",
                                 "location must be a string when present"))
        if item.get("confidence") not in CONFIDENCE_LEVELS:
            issues.append(_issue("invalid_field_evidence", f"{item_path}.confidence",
                                 "confidence must be high, medium or low"))
    for key in scalar_keys:
        if entry[key] is not None and key not in evidence:
            issues.append(_issue(
                "missing_field_evidence", f"{path}.field_evidence.{key}",
                f"populated field '{key}' has no field_evidence entry"))


def _check_record(entry, defaults: dict, scalar_keys: tuple, path: str,
                  issues: list) -> None:
    _check_keys(entry, tuple(defaults.keys()), path, issues)
    for key, default in defaults.items():
        entry.setdefault(key, dict() if key == "field_evidence" else default)
    for key in scalar_keys:
        _normalize_scalar(entry, key, path, issues)
    confidence = entry["confidence"]
    if confidence not in CONFIDENCE_LEVELS:
        issues.append(_issue("confidence_invalid", f"{path}.confidence",
                             "confidence must be high, medium or low"))
    _check_evidence(entry, scalar_keys, path, issues)


def _check_email(entry: dict, contacts_len: int | None, path: str, issues: list) -> None:
    _check_keys(entry, EMAIL_KEYS, path, issues)
    for key, default in EMAIL_DEFAULTS.items():
        entry.setdefault(key, [] if isinstance(default, list) else default)
    for key in EMAIL_SCALAR_KEYS:
        _normalize_scalar(entry, key, path, issues)
    if not isinstance(entry["has_signature"], bool):
        issues.append(_issue("type_error", f"{path}.has_signature",
                             "has_signature must be a boolean"))
    for key in EMAIL_LIST_KEYS:
        value = entry[key]
        if not isinstance(value, list):
            issues.append(_issue("type_error", f"{path}.{key}", "expected an array"))
            continue
        if key == "contact_indices":
            for i, index in enumerate(value):
                if not isinstance(index, int) or isinstance(index, bool):
                    issues.append(_issue("type_error", f"{path}.{key}[{i}]",
                                         "contact_indices entries must be integers"))
                elif contacts_len is not None and not 0 <= index < contacts_len:
                    issues.append(_issue(
                        "contact_indices_out_of_range", f"{path}.{key}[{i}]",
                        "index must reference an entry of this response's contacts[]"))
        else:
            for i, item in enumerate(value):
                if not isinstance(item, str):
                    issues.append(_issue("type_error", f"{path}.{key}[{i}]",
                                         "array entries must be strings"))


def _check_call_logs(call_logs: list, allow_call_logs: bool, issues: list) -> None:
    if call_logs and not allow_call_logs:
        issues.append(_issue(
            "call_logs_not_allowed", "call_logs",
            "source has no structured call columns; call_logs must be empty"))
        return
    for i, entry in enumerate(call_logs):
        path = f"call_logs[{i}]"
        if not isinstance(entry, dict):
            issues.append(_issue("type_error", path, "each call log must be an object"))
            continue
        _check_keys(entry, CALL_LOG_KEYS, path, issues)
        for key, value in entry.items():
            if value is None:
                continue
            if key == "duration_minutes":
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    issues.append(_issue("type_error", f"{path}.{key}",
                                         "duration_minutes must be a number"))
            elif not isinstance(value, str):
                issues.append(_issue("type_error", f"{path}.{key}",
                                     "expected string or null"))


def validate_extraction_result(payload, source_type: str, *,
                               allow_call_logs: bool = False
                               ) -> tuple[dict | None, list[dict]]:
    """Gate a model response against crm-extraction.v1.

    Returns (validated_payload, []) on full acceptance, else (None, issues).
    No partial acceptance: any violation rejects the whole payload.
    """
    if isinstance(payload, str):
        import json
        try:
            payload = json.loads(payload)
        except ValueError:
            return None, [_issue("type_error", "$", "response is not valid JSON")]
    if not isinstance(payload, dict):
        return None, [_issue("type_error", "$", "payload must be a JSON object")]

    data = copy.deepcopy(payload)
    issues: list[dict] = []
    _scan_banned(data, "$", issues)

    for key in TOP_LEVEL_KEYS:
        if key not in data:
            issues.append(_issue("missing_key", key, "required top-level key is absent"))
    for key in data:
        if key in TOP_LEVEL_KEYS:
            continue
        if key in BANNED_DB_KEYS:
            continue  # reported by _scan_banned
        if key == "contact_indices":
            issues.append(_issue("contact_indices_scope", "contact_indices",
                                 "contact_indices is only valid inside emails[] (D-021)"))
            continue
        issues.append(_issue("unexpected_key", key, "unsupported top-level key"))

    if "schema_version" in data and data["schema_version"] != SCHEMA_VERSION:
        issues.append(_issue("schema_version_invalid", "schema_version",
                             f"expected '{SCHEMA_VERSION}'"))
    if "source_type" in data and data["source_type"] != source_type:
        issues.append(_issue("source_type_mismatch", "source_type",
                             f"expected '{source_type}'"))

    for key in LIST_KEYS:
        if key in data and not isinstance(data[key], list):
            issues.append(_issue("type_error", key, "expected an array"))

    if isinstance(data.get("companies"), list):
        for i, entry in enumerate(data["companies"]):
            if not isinstance(entry, dict):
                issues.append(_issue("type_error", f"companies[{i}]",
                                     "each company must be an object"))
                continue
            _check_record(entry, COMPANY_DEFAULTS, COMPANY_SCALAR_KEYS,
                          f"companies[{i}]", issues)
    if isinstance(data.get("contacts"), list):
        contacts_len = len(data["contacts"])
        for i, entry in enumerate(data["contacts"]):
            if not isinstance(entry, dict):
                issues.append(_issue("type_error", f"contacts[{i}]",
                                     "each contact must be an object"))
                continue
            _check_record(entry, CONTACT_DEFAULTS, CONTACT_SCALAR_KEYS,
                          f"contacts[{i}]", issues)
    else:
        contacts_len = None
    if isinstance(data.get("emails"), list):
        for i, entry in enumerate(data["emails"]):
            if not isinstance(entry, dict):
                issues.append(_issue("type_error", f"emails[{i}]",
                                     "each email must be an object"))
                continue
            _check_email(entry, contacts_len, f"emails[{i}]", issues)

    if isinstance(data.get("call_logs"), list):
        _check_call_logs(data["call_logs"], allow_call_logs, issues)

    if isinstance(data.get("unmapped_fields"), list):
        for i, item in enumerate(data["unmapped_fields"]):
            if not isinstance(item, (str, dict)):
                issues.append(_issue("array_item_invalid", f"unmapped_fields[{i}]",
                                     "entries must be strings or objects"))
    if isinstance(data.get("warnings"), list):
        for i, item in enumerate(data["warnings"]):
            if not isinstance(item, str):
                issues.append(_issue("array_item_invalid", f"warnings[{i}]",
                                     "entries must be strings"))

    if issues:
        return None, issues
    return data, []
