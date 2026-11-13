"""Tests for Phase 1 dedup comparison layer (services/dedup)."""

from services import dedup
from services.keys import (
    normalize_email, phone_key, name_key, company_key, website_key,
)


class TestReuseSharedCore:

    def test_email_key_delegates_to_shared_rule(self):
        assert dedup.email_key("  Ravi@Acme.IN ") == "ravi@acme.in"


class TestNormalizers:

    def test_name_key_strips_and_lowercases(self):
        assert name_key("  Ravi   Kumar ") == "ravi kumar"

    def test_name_key_strips_honorifics(self):
        assert name_key("Mr. Ravi Kumar") == "ravi kumar"
        assert name_key("Dr Ravi Kumar") == "ravi kumar"

    def test_company_key_strips_legal_suffixes(self):
        assert company_key("Acme Drilling Pvt Ltd") == "acme drilling"
        assert company_key("The Acme Co") == "acme"

    def test_website_key_normalizes(self):
        assert website_key("https://www.Acme.in/about") == "acme.in"

    def test_empty_values_return_none(self):
        assert name_key("") is None
        assert name_key(None) is None
        assert company_key("") is None
        assert dedup.email_key("") is None

    def test_phone_key_collapse_india_variance(self):
        a = phone_key("+91 98765 43210")
        b = phone_key("09876543210")
        c = phone_key("9876543210")
        assert a == b == c == "9876543210"


def band(a, b):
    return dedup.compare(a, b)["band"]


def score(a, b):
    return dedup.compare(a, b)["score"]


class TestExactDuplicate:

    def test_same_email_is_exact(self):
        m = dedup.compare(
            {"name": "Ravi Kumar", "email": "ravi@acme.in"},
            {"name": "Ravi Kumar", "email": "RAVI@acme.in"},
        )
        assert m["band"] == dedup.EXACT_DUPLICATE
        assert m["score"] == 1.0
        assert m["matched_on"] == "email"

    def test_same_phone_formats_is_exact(self):
        m = dedup.compare(
            {"name": "Ravi", "phone_primary": "+91 98765 43210"},
            {"name": "Ravi", "phone_primary": "09876543210"},
        )
        assert m["band"] == dedup.EXACT_DUPLICATE
        assert m["score"] == 1.0

    def test_zero_prefix_and_plus91_equivalent(self):
        base = {"phone_primary": "9876543210"}
        assert band(base, {"phone_primary": "+91 9876543210"}) == dedup.EXACT_DUPLICATE
        assert band(base, {"phone_primary": "09876543210"}) == dedup.EXACT_DUPLICATE

    def test_name_and_company_alone_is_probable_not_certain(self):
        m = dedup.compare(
            {"name": "Ravi Kumar", "company": "Acme Drilling"},
            {"name": "Ravi  Kumar", "company": "Acme Drilling Pvt Ltd"},
        )
        assert m["band"] == dedup.PROBABLE_DUPLICATE
        assert m["score"] == 0.9


class TestProbableDuplicate:

    def test_name_plus_company_variant_is_probable(self):
        m = dedup.compare(
            {"name": "Krishna Reddy", "company": "Acme Industries"},
            {"name": "Krishna Reddy", "company": "Acme Industries Pvt Ltd"},
        )
        assert m["band"] == dedup.PROBABLE_DUPLICATE

    def test_same_name_different_email_not_certain(self):
        m = dedup.compare(
            {"name": "Ravi Kumar", "email": "ravi@acme.in"},
            {"name": "Ravi Kumar", "email": "ravi@othercorp.in"},
        )
        assert m["band"] != dedup.EXACT_DUPLICATE
        assert m["score"] < 1.0

    def test_name_only_exact_never_certain(self):
        m = dedup.compare({"name": "Ravi Kumar"}, {"name": "Ravi Kumar"})
        assert m["band"] == dedup.PROBABLE_DUPLICATE
        assert m["band"] != dedup.EXACT_DUPLICATE
        assert m["score"] == 0.6

    def test_fuzzy_name_is_probable_below_one(self):
        m = dedup.compare(
            {"name": "Krishna Reddy", "phone_primary": "1111111111"},
            {"name": "Krishna Reddi", "phone_primary": "2222222222"},
        )
        assert m["band"] == dedup.PROBABLE_DUPLICATE
        assert m["score"] < 1.0


class TestConflict:

    def test_same_email_different_names_conflicts(self):
        m = dedup.compare(
            {"name": "Ravi Kumar", "email": "x@acme.in"},
            {"name": "Suresh Babu", "email": "x@acme.in"},
        )
        assert m["band"] == dedup.CONFLICT

    def test_same_phone_different_names_conflicts(self):
        m = dedup.compare(
            {"name": "Ravi Kumar", "phone_primary": "9876543210"},
            {"name": "Suresh Babu", "phone_primary": "9876543210"},
        )
        assert m["band"] == dedup.CONFLICT

    def test_same_name_company_different_email_conflicts(self):
        m = dedup.compare(
            {"name": "Ravi Kumar", "company": "Acme", "email": "a@acme.in"},
            {"name": "Ravi Kumar", "company": "Acme Pvt Ltd", "email": "b@acme.in"},
        )
        assert m["band"] == dedup.CONFLICT


class TestUnique:

    def test_same_name_different_company_is_unique(self):
        m = dedup.compare(
            {"name": "Ravi Kumar", "company": "Acme Drilling"},
            {"name": "Ravi Kumar", "company": "Zenith Infra"},
        )
        assert m["band"] == dedup.UNIQUE
        assert m["score"] == 0.0

    def test_different_everything_is_unique(self):
        m = dedup.compare(
            {"name": "Ravi Kumar", "phone_primary": "9876543210",
             "email": "r@acme.in", "company": "Acme"},
            {"name": "Meena Iyer", "phone_primary": "9123456780",
             "email": "m@zen.in", "company": "Zenith"},
        )
        assert m["band"] == dedup.UNIQUE

    def test_empty_records_are_unique(self):
        assert band({}, {}) == dedup.UNIQUE

    def test_non_dict_input_is_unique(self):
        assert band("not a dict", {}) == dedup.UNIQUE


class TestFindMatches:

    def test_excludes_unique(self):
        matches = dedup.find_matches(
            {"name": "Ravi Kumar", "company": "Acme"},
            [{"name": "Ravi Kumar", "company": "Zenith"}],
        )
        assert matches == []

    def test_reports_match_index_band_and_score(self):
        matches = dedup.find_matches(
            {"name": "Ravi Kumar", "email": "r@acme.in"},
            [{"name": "Meena Iyer", "email": "m@zen.in"},
             {"name": "Ravi Kumar", "email": "R@acme.in"}],
        )
        assert len(matches) == 1
        m = matches[0]
        assert m["index"] == 1
        assert m["band"] == dedup.EXACT_DUPLICATE
        assert m["score"] == 1.0

    def test_sorted_by_score_desc(self):
        matches = dedup.find_matches(
            {"name": "Ravi Kumar", "company": "Acme Drilling"},
            [{"name": "Ravi Kumar"},                      # name-only 0.6
             {"name": "Ravi Kumar", "company": "Acme Drilling"},  # 0.9
             {"name": "Meena Iyer"}],                     # UNIQUE, excluded
        )
        scores = [m["score"] for m in matches]
        assert scores == sorted(scores, reverse=True)
        assert scores == [0.9, 0.6]

    def test_reports_only_never_decides(self):
        candidate = {"name": "Ravi Kumar", "email": "r@acme.in"}
        records = [{"name": "Ravi Kumar", "email": "r@acme.in"}]
        result = dedup.find_matches(candidate, records)
        assert isinstance(result, list)
        assert all(isinstance(m, dict) for m in result)
        # inputs untouched — the engine never merges or rewrites
        assert candidate == {"name": "Ravi Kumar", "email": "r@acme.in"}
        assert records == [{"name": "Ravi Kumar", "email": "r@acme.in"}]

    def test_empty_inputs(self):
        assert dedup.find_matches({"name": "x"}, []) == []


class TestFuzzyNeverAutoCertain:

    def test_fuzzy_pairs_never_reach_certain_threshold(self):
        pairs = [
            ({"name": "Krishna Reddy"}, {"name": "Krishna Reddi"}),
            ({"name": "Ravi Kumar", "company": "Acme"},
             {"name": "Ravi Kumarr", "company": "Acme"}),
            ({"name": "Meena Iyer", "phone_primary": "9123456780"},
             {"name": "Meena Iyer", "phone_primary": "9123456781"}),
        ]
        for a, b in pairs:
            m = dedup.compare(a, b)
            assert m["band"] != dedup.EXACT_DUPLICATE, (a, b)
            if m["band"] == dedup.PROBABLE_DUPLICATE:
                assert m["score"] < 1.0
