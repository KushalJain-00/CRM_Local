# tests/test_keys.py — the one identity-key implementation, pinned hard.
import pytest

from services.keys import (
    normalize_email, normalize_phone, phone_key, name_key, company_key,
    website_key, normalize_name, record_keys, identity_key, is_duplicate,
)
from services import dedup, staging


class TestEmail:
    def test_trim_and_case(self):
        assert normalize_email("  Ravi@Acme.IN ") == "ravi@acme.in"

    def test_empty_and_none(self):
        assert normalize_email(None) == ""
        assert normalize_email("") == ""


class TestPhone:
    @pytest.mark.parametrize("raw,key", [
        ("+91 98765 43210", "9876543210"),
        ("09876543210", "9876543210"),
        ("9876543210", "9876543210"),
        ("+91-98765-43210", "9876543210"),
        ("(022) 1234 5678", "2212345678"),
    ])
    def test_india_variance_collapses(self, raw, key):
        assert phone_key(raw) == key

    @pytest.mark.parametrize("raw", [None, "", "123", "12"])
    def test_too_short_or_missing_is_none(self, raw):
        assert phone_key(raw) is None

    def test_normalize_phone_keeps_all_digits(self):
        assert normalize_phone("+91 (22) 1234-5678") == "912212345678"


class TestNameKey:
    @pytest.mark.parametrize("raw", [
        "Mr. Ravi Kumar", "MR RAVI  KUMAR", "Dr Ravi Kumar", "Ravi Kumar",
        "Shri Ravi Kumar",
    ])
    def test_honorifics_and_ws_case_collapse(self, raw):
        assert name_key(raw) == "ravi kumar"

    def test_punctuation_collapses(self):
        assert name_key("Ravi, Kumar.") == "ravi kumar"
        assert name_key("  RAJU   DAS  ") == "raju das"

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_empty_is_none(self, raw):
        assert name_key(raw) is None

    def test_honorific_without_name_stays_literal(self):
        # established semantics: a bare honorific still keys as "mr"
        assert name_key("Mr.") == "mr"

    def test_plain_normalize_name_keeps_honorific(self):
        # is_duplicate's comparison form is not honorific-stripped
        assert normalize_name("Mr. Ravi Kumar") == "mr. ravi kumar"


class TestCompanyAndWebsite:
    def test_legal_tokens_removed_case_insensitive(self):
        assert company_key("Acme Pvt Ltd") == "acme"
        assert company_key("ACME PRIVATE LIMITED") == "acme"
        assert company_key("Globex, Inc.") == "globex"

    def test_company_missing_is_none(self):
        assert company_key(None) is None
        assert company_key("Pvt Ltd") is None

    def test_website_strips_scheme_www_path_port(self):
        assert website_key("https://www.Acme.in/products?q=1") == "acme.in"
        assert website_key("acme.in:8080/about") == "acme.in"
        assert website_key("") is None


class TestRecordKeys:
    def test_complete_keys_from_contact_dict(self):
        keys = record_keys({
            "name": "Mr. Ravi Kumar",
            "email_primary": "  Ravi@Acme.IN ",
            "phone_primary": "+91 98765 43210",
            "company": "Acme Pvt Ltd",
            "website": "https://www.acme.in/a",
        })
        assert keys == {
            "email_key": "ravi@acme.in",
            "phone_key": "9876543210",
            "name_key": "ravi kumar",
            "company_key": "acme",
            "website_key": "acme.in",
        }

    def test_missing_fields_yield_null_keys(self):
        keys = record_keys({})
        assert keys == {"email_key": None, "phone_key": None, "name_key": None,
                        "company_key": None, "website_key": None}

    def test_contract_vocab_field_fallbacks(self):
        # crm-extraction.v1 uses email/company_name; record_keys accepts both
        keys = record_keys({"email": "A@B.in", "company_name": "Acme Ltd"})
        assert keys["email_key"] == "a@b.in"
        assert keys["company_key"] == "acme"


class TestPriority:
    def test_email_wins_over_phone(self):
        k = identity_key({"email_primary": "a@b.in", "phone_primary": "9876543210"})
        assert k == ("e", "a@b.in")

    def test_phone_wins_over_name_company(self):
        k = identity_key({"phone_primary": "9876543210",
                          "name": "Ravi Kumar", "company": "Acme"})
        assert k == ("p", "9876543210")

    def test_name_company_is_last_resort(self):
        k = identity_key({"name": "Ravi Kumar", "company": "Acme"})
        assert k == ("n", "ravi kumar", "acme")

    def test_all_missing_is_unidentified(self):
        assert identity_key({}) == ("n", None, None)

    def test_ingestion_paths_agree(self):
        # an .eml-derived contact dict and a .csv-derived one must share identity
        eml = {"name": "Mr. Ravi Kumar", "email": "RAVI@x.in", "company": "Acme Ltd"}
        csv = {"name": "Ravi Kumar", "email_primary": "ravi@x.in", "company": "Acme Pvt Ltd"}
        assert identity_key(eml) == identity_key(csv)


class TestWriterConsistency:
    def test_staged_and_canonical_keys_agree(self, data_dir):
        import db
        import sqlite3
        con = db.connect("crm")
        try:
            staging.stage_contacts(
                con, [{"name": "Mr. Ravi Kumar", "email_primary": "Ravi@Acme.in",
                       "company": "Acme Pvt Ltd", "source_file": "a.csv"}],
                source_type="csv", source_file="a.csv",
            )
            row = con.execute("SELECT email_key, phone_key, name_key, company_key "
                              "FROM staged_contacts").fetchone()
            expected = record_keys({"name": "Mr. Ravi Kumar",
                                    "email_primary": "Ravi@Acme.in",
                                    "company": "Acme Pvt Ltd"})
            assert tuple(row) == (expected["email_key"], expected["phone_key"],
                                  expected["name_key"], expected["company_key"])
        finally:
            con.close()

    def test_dedup_finds_canonical_by_honorific_variant(self, data_dir):
        import db
        con = db.connect("crm")
        try:
            keys = record_keys({"name": "Ravi Kumar", "company": "Acme",
                                "email_primary": "ravi@acme.in"})
            con.execute(
                "INSERT INTO contacts (name, email_primary, company, email_key, phone_key,"
                " name_key, company_key, website_key, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("Ravi Kumar", "ravi@acme.in", "Acme", keys["email_key"], keys["phone_key"],
                 keys["name_key"], keys["company_key"], keys["website_key"],
                 "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))
            con.commit()
            band, candidates = staging._dedup_vs_canonical(
                con, {"name": "Dr. Ravi Kumar", "company": "Acme Pvt Ltd",
                      "email_primary": "ravi@acme.in"})
            assert band == dedup.EXACT_DUPLICATE
            assert candidates
        finally:
            con.close()


class TestIsDuplicate:
    def test_email_hit(self):
        assert is_duplicate("a@b.in", None, {"a@b.in"}, set()) == "email"

    def test_phone_containment_hit(self):
        assert is_duplicate(None, "+91 98765 43210", set(), {"919876543210"}) == "phone"

    def test_name_only_needs_existing_names(self):
        assert is_duplicate(None, None, set(), set(), "Ravi Kumar", {"ravi kumar"}) == "name"
        assert is_duplicate(None, None, set(), set(), "Ravi Kumar") is None
