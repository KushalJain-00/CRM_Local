"""Tests for Phase 1 contract gate (services/contract)."""

import copy
import json

import pytest

from services.contract import SCHEMA_VERSION, validate_extraction_result
from services.prompts import EXTRACTION_CONTRACT


def make_valid_payload(source_type="spreadsheet"):
    return {
        "schema_version": SCHEMA_VERSION,
        "source_type": source_type,
        "companies": [],
        "contacts": [
            {"name": "Ravi Kumar", "company_name": "Acme Drilling",
             "confidence": "high",
             "field_evidence": {
                 "name": {"excerpt": "Ravi Kumar", "confidence": "high"},
                 "company_name": {"excerpt": "Acme Drilling", "confidence": "high"},
             }},
        ],
        "emails": [],
        "call_logs": [],
        "unmapped_fields": [],
        "warnings": [],
    }


def codes(issues):
    return [i["code"] for i in issues]


class TestValidPayloads:

    def test_valid_payload_passes(self):
        validated, issues = validate_extraction_result(make_valid_payload(), "spreadsheet")
        assert issues == []
        assert validated["contacts"][0]["name"] == "Ravi Kumar"

    def test_minimal_payload_passes(self):
        payload = make_valid_payload("csv")
        payload["contacts"] = [{}]
        validated, issues = validate_extraction_result(payload, "csv")
        assert issues == []
        assert validated["contacts"][0]["confidence"] == "low"

    def test_empty_payload_structure_allowed(self):
        payload = {"schema_version": SCHEMA_VERSION, "source_type": "pdf",
                   "companies": [], "contacts": [], "emails": [],
                   "call_logs": [], "unmapped_fields": [], "warnings": []}
        validated, issues = validate_extraction_result(payload, "pdf")
        assert issues == []
        assert validated == payload

    def test_json_string_input_accepted(self):
        raw = json.dumps(make_valid_payload())
        validated, issues = validate_extraction_result(raw, "spreadsheet")
        assert issues == []
        assert validated["contacts"][0]["name"] == "Ravi Kumar"

    def test_non_object_payload_rejected(self):
        validated, issues = validate_extraction_result(["not", "a", "dict"], "csv")
        assert validated is None
        assert codes(issues) == ["type_error"]

    def test_no_partial_acceptance_returns_none(self):
        payload = make_valid_payload()
        payload["bogus_top"] = 1
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "unexpected_key" in codes(issues)

    def test_input_not_mutated_on_success(self):
        payload = make_valid_payload()
        before = copy.deepcopy(payload)
        validate_extraction_result(payload, "spreadsheet")
        assert payload == before

    def test_input_not_mutated_on_failure(self):
        payload = make_valid_payload()
        payload["session_id"] = "abc"
        before = copy.deepcopy(payload)
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert issues
        assert payload == before


class TestSchemaVersion:

    def test_wrong_schema_version_rejected(self):
        payload = make_valid_payload()
        payload["schema_version"] = "crm-extraction.v2"
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "schema_version_invalid" in codes(issues)

    def test_missing_schema_version_rejected(self):
        payload = make_valid_payload()
        del payload["schema_version"]
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "missing_key" in codes(issues)

    def test_missing_any_top_level_key_rejected(self):
        payload = make_valid_payload()
        del payload["warnings"]
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "missing_key" in codes(issues)


class TestBannedDbKeys:

    @pytest.mark.parametrize("key", ["session_id", "created_at", "user_id", "id"])
    def test_db_or_session_key_rejected_anywhere(self, key):
        payload = make_valid_payload()
        payload[key] = "x"
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "llm_emitted_db_field" in codes(issues)

    def test_contact_db_id_rejected(self):
        payload = make_valid_payload()
        payload["contacts"][0]["id"] = 42
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "llm_emitted_db_field" in codes(issues)

    def test_prompt_contract_never_declares_banned_keys(self):
        text = json.dumps(EXTRACTION_CONTRACT)
        for key in ("session_id", "created_at", "contact_id", "row_id"):
            assert f'"{key}"' not in text


class TestKeyScope:

    def test_extra_top_level_key_rejected(self):
        payload = make_valid_payload()
        payload["extra"] = 1
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "unexpected_key" in codes(issues)

    def test_extra_contact_key_rejected(self):
        payload = make_valid_payload()
        payload["contacts"][0]["nickname"] = "x"
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "unexpected_key" in codes(issues)

    def test_contact_indices_top_level_rejected_d021(self):
        payload = make_valid_payload()
        payload["contact_indices"] = [0, 1]
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "contact_indices_scope" in codes(issues)

    def test_contact_indices_inside_contact_rejected_d021(self):
        payload = make_valid_payload()
        payload["contacts"][0]["contact_indices"] = [3]
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "contact_indices_scope" in codes(issues)

    def test_contract_declares_contact_indices_emails_only(self):
        allowed_top = set(EXTRACTION_CONTRACT.keys())
        contact_keys = set(EXTRACTION_CONTRACT["contacts"][0].keys())
        email_keys = set(EXTRACTION_CONTRACT["emails"][0].keys())
        assert "contact_indices" in email_keys
        assert "contact_indices" not in contact_keys
        assert "contact_indices" not in allowed_top


class TestTypeErrors:

    def test_contacts_must_be_list(self):
        payload = make_valid_payload()
        payload["contacts"] = "Ravi"
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "type_error" in codes(issues)

    def test_contact_name_must_be_string_or_null(self):
        payload = make_valid_payload()
        payload["contacts"][0]["name"] = 123
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "type_error" in codes(issues)

    def test_warnings_must_be_list(self):
        payload = make_valid_payload()
        payload["warnings"] = "careful"
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "type_error" in codes(issues)

    def test_contact_must_be_object(self):
        payload = make_valid_payload()
        payload["contacts"][0] = "Ravi Kumar"
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "type_error" in codes(issues)


class TestEvidence:

    def test_missing_evidence_for_populated_field_rejected(self):
        payload = make_valid_payload()
        payload["contacts"][0]["field_evidence"] = {"name": {
            "excerpt": "Ravi Kumar", "confidence": "high"}}  # company_name missing
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "missing_field_evidence" in codes(issues)

    def test_null_fields_need_no_evidence(self):
        payload = make_valid_payload()
        payload["contacts"] = [{"name": None, "confidence": "low",
                                "field_evidence": {}}]
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert issues == []

    def test_evidence_must_be_object(self):
        payload = make_valid_payload()
        payload["contacts"][0]["field_evidence"] = ["name"]
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "type_error" in codes(issues)

    def test_evidence_requires_nonempty_excerpt(self):
        payload = make_valid_payload()
        payload["contacts"][0]["field_evidence"]["name"]["excerpt"] = ""
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "invalid_field_evidence" in codes(issues)

    def test_evidence_for_unknown_field_rejected(self):
        payload = make_valid_payload()
        payload["contacts"][0]["field_evidence"]["nickname"] = {
            "excerpt": "x", "confidence": "high"}
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "invalid_field_evidence" in codes(issues)


class TestCallLogs:

    def test_nonempty_call_logs_rejected_on_spreadsheet_by_default(self):
        payload = make_valid_payload()
        payload["call_logs"] = [{"contact_name": "Ravi Kumar"}]
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "call_logs_not_allowed" in codes(issues)

    def test_empty_call_logs_always_allowed(self):
        payload = make_valid_payload("eml")
        payload["call_logs"] = []
        validated, issues = validate_extraction_result(payload, "eml")
        assert issues == []

    def test_call_logs_allowed_when_explicitly_permitted(self):
        payload = make_valid_payload()
        payload["call_logs"] = [{"contact_name": "Ravi Kumar",
                                 "duration_minutes": 15}]
        validated, issues = validate_extraction_result(
            payload, "spreadsheet", allow_call_logs=True)
        assert issues == []


class TestConfidenceAndIndices:

    @pytest.mark.parametrize("value", ["0.95", 1.5, None])
    def test_confidence_must_be_high_medium_low(self, value):
        payload = make_valid_payload()
        payload["contacts"][0]["confidence"] = value
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "confidence_invalid" in codes(issues)

    @pytest.mark.parametrize("value", ["high", "medium", "low"])
    def test_valid_confidence_levels_pass(self, value):
        payload = make_valid_payload()
        payload["contacts"][0]["confidence"] = value
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert issues == []

    def test_source_type_mismatch_rejected(self):
        payload = make_valid_payload(source_type="spreadsheet")
        payload["source_type"] = "pdf"
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "source_type_mismatch" in codes(issues)

    def test_contact_index_out_of_range_rejected(self):
        payload = make_valid_payload()
        payload["emails"] = [{"contact_indices": [99]}]
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert validated is None
        assert "contact_indices_out_of_range" in codes(issues)

    def test_valid_contact_index_accepted(self):
        payload = make_valid_payload()
        payload["emails"] = [{"contact_indices": [0]}]
        validated, issues = validate_extraction_result(payload, "spreadsheet")
        assert issues == []


class TestContractInternals:

    def test_json_contract_round_trips(self):
        assert json.loads(json.dumps(EXTRACTION_CONTRACT)) == EXTRACTION_CONTRACT

    def test_issue_shape(self):
        payload = make_valid_payload()
        payload["extra"] = 1
        _, issues = validate_extraction_result(payload, "spreadsheet")
        for key in ("code", "path", "message"):
            assert key in issues[0]
