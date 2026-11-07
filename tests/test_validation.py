"""Tests for Phase 1 field validation (services/validation)."""

import copy

from services.validation import (
    ISSUE_CATEGORIES,
    classify_phone,
    detect_phone_country,
    validate_company,
    validate_email,
    validate_industry,
    validate_name,
    validate_phone,
    validate_pincode,
    validate_record,
)


# --- Spec-mandated concrete cases (ADVANCED_EXTRACTION_SPEC.md 5.4) -------------

class TestSpecExamples:

    def test_llm_generated_artifact_email_is_suspicious(self):
        issues = validate_email("image001.png@01dd4100.ede")
        assert issues
        assert issues[0]["category"] == "SUSPICIOUS"

    def test_sentence_as_name_is_suspicious(self):
        issues = validate_name("share the quotation asap.")
        assert issues
        assert issues[0]["category"] == "SUSPICIOUS"

    def test_metadata_chunk_as_company_is_suspicious(self):
        value = "Depth.- 900 FT. Borewell Pipeline Size.- 2.5 Inc"
        issues = validate_company(value)
        assert issues
        assert issues[0]["category"] == "SUSPICIOUS"


class TestIndianPhoneVariants:

    def test_valid_indian_variants_pass(self):
        variants = [
            "+91 98765 43210",
            "09876543210",
            "98765 43210",
            "9876543210",
            "+91-98765-43210",
            "(098765) 43210",
            "+919876543210",
            "tel:9876543210",
        ]
        for value in variants:
            issues = validate_phone(value)
            assert issues == [], (value, issues)

    def test_valid_landline_variants_pass(self):
        for value in ["011 2345 6789", "+91 40 1234 5678"]:
            issues = validate_phone(value)
            assert issues == [], (value, issues)

    def test_indian_mobile_classified(self):
        assert classify_phone("9876543210") == "mobile"
        assert classify_phone("+919876543210") == "mobile"
        assert classify_phone("09876543210") == "mobile"


class TestInternationalNoFalsePositives:

    def test_unfamiliar_address_passes(self):
        from services.validation import validate_address
        assert validate_address("221B Baker Street, London NW1 6XE") == []

    def test_international_pincodes_pass(self):
        for value in ["NW1 6XE", "SW1A 1AA", "62704", "04101", "D-12345"]:
            issues = validate_pincode(value)
            assert issues == [], (value, issues)

    def test_international_phones_pass(self):
        for value in ["+1 202 555 0100", "+44 20 7946 0958"]:
            issues = validate_phone(value)
            assert issues == [], (value, issues)

    def test_foreign_prefix_classified_international(self):
        assert classify_phone("+1 555 0100") == "international"


class TestIssueShape:

    def test_issue_dict_keys(self):
        issues = validate_email("not-an-email")
        assert issues
        for key in ("category", "field", "value", "message", "severity"):
            assert key in issues[0], key

    def test_categories_are_exact(self):
        assert set(ISSUE_CATEGORIES) == {
            "INVALID",
            "SUSPICIOUS",
            "MISSING",
            "UNCERTAIN",
            "FIELD_MAPPING_ERROR",
            "POSSIBLE_DUPLICATE",
            "CONFLICT",
        }

    def test_issue_category_within_enumeration(self):
        for issue in validate_email("not-an-email") + validate_phone("12"):
            assert issue["category"] in ISSUE_CATEGORIES


class TestCategoriesReachable:

    def test_invalid(self):
        assert validate_email("not-an-email")[0]["category"] == "INVALID"

    def test_missing(self):
        issues = validate_record({"name": "Ravi"})
        assert any(i["category"] == "MISSING" for i in issues)

    def test_record_with_identity_not_missing(self):
        issues = validate_record({"name": "Ravi", "phone_primary": "9876543210"})
        assert not any(i["category"] == "MISSING" for i in issues)

    def test_suspicious(self):
        assert validate_email("image001.png@01dd4100.ede")[0]["category"] == "SUSPICIOUS"

    def test_uncertain_short_phone(self):
        assert validate_phone("1234567")[0]["category"] == "UNCERTAIN"

    def test_uncertain_reference_number_next_to_digits(self):
        issues = validate_phone("SR.NO 9876543210")
        assert issues[0]["category"] == "UNCERTAIN"

    def test_field_mapping_error_industry_hold_value(self):
        assert validate_industry("Sales Manager")[0]["category"] == "FIELD_MAPPING_ERROR"

    def test_possible_duplicate_equal_primary_and_secondary_email(self):
        issues = validate_record({"email_primary": "ravi@acme.in",
                                  "email_secondary": "RAVI@acme.in"})
        assert any(i["category"] == "POSSIBLE_DUPLICATE" for i in issues)

    def test_conflict_phone_country_mismatch(self):
        issues = validate_record({"phone_country": "US",
                                  "phone_primary": "+91 98765 43210"})
        assert any(i["category"] == "CONFLICT" for i in issues)

    def test_all_categories_reachable(self):
        reached = set()
        reached |= {i["category"] for i in validate_email("not-an-email")}
        reached |= {i["category"] for i in validate_record({"name": "Ravi"})}
        reached |= {i["category"] for i in validate_email("image001.png@01dd4100.ede")}
        reached |= {i["category"] for i in validate_phone("1234567")}
        reached |= {i["category"] for i in validate_industry("Sales Manager")}
        reached |= {i["category"] for i in validate_record(
            {"email_primary": "r@x.in", "email_secondary": "r@x.in"})}
        reached |= {i["category"] for i in validate_record(
            {"phone_country": "US", "phone_primary": "+91 98765 43210"})}
        assert reached == set(ISSUE_CATEGORIES)

    def test_mixed_categories_in_one_record(self):
        record = {"name": "share the quotation asap.",
                  "pincode": "12",
                  "industry": "Sales Manager"}
        cats = {i["category"] for i in validate_record(record)}
        assert cats <= set(ISSUE_CATEGORIES)
        assert {"SUSPICIOUS", "INVALID", "MISSING", "FIELD_MAPPING_ERROR"} <= cats


class TestNoMutation:

    def test_record_not_mutated(self):
        record = {"name": "share the quotation asap.", "company_name": "",
                  "phone_primary": "", "email_primary": ""}
        before = copy.deepcopy(record)
        validate_record(record)
        assert record == before

    def test_raw_value_kept_verbatim_in_issue(self):
        raw = "image001.png@01dd4100.ede"
        issues = validate_email(raw)
        assert issues[0]["value"] == raw

    def test_flagged_values_not_dropped_from_record(self):
        record = {"name": "share the quotation asap.", "email_primary": "r@x.in"}
        validate_record(record)
        assert record["name"] == "share the quotation asap."


class TestClassifyPhone:

    def test_mobile_and_landline(self):
        assert classify_phone("9876543210") == "mobile"
        assert classify_phone("2345678901") == "landline"

    def test_whatsapp_when_labelled(self):
        assert classify_phone("whatsapp 9876543210") == "whatsapp"

    def test_invalid_when_no_digits(self):
        assert classify_phone("abc") == "unknown"
        assert classify_phone("") == "unknown"

    def test_unknown_when_too_short(self):
        assert classify_phone("12345") == "unknown"

    def test_foreign_operator_is_international(self):
        assert classify_phone("+1 555 0100") == "international"


class TestDetectPhoneCountry:

    def test_no_country_for_plain_number(self):
        assert detect_phone_country("9876543210") is None
        assert detect_phone_country("09876543210") is None

    def test_country_only_from_explicit_prefix(self):
        assert detect_phone_country("+91 98765 43210") == "IN"
        assert detect_phone_country("+1 555 0100") == "US"
        assert detect_phone_country("+44 20 7946 0958") == "UK"

    def test_none_for_empty(self):
        assert detect_phone_country("") is None
