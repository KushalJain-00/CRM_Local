# tests/test_reliability_config.py — reliability spec: defaults, bounds, persistence.
import pytest
from fastapi import HTTPException

import llm
import api.settings as settings


class TestSpecCoherence:
    def test_defaults_cover_exactly_the_specced_fields(self):
        defaults = llm.default_reliability()
        assert set(defaults) == set(llm.RELIABILITY_FIELDS) == set(llm.RELIABILITY_DESCRIPTIONS)

    def test_defaults_within_bounds(self):
        defaults = llm.default_reliability()
        for key, value in defaults.items():
            lo, hi = llm.RELIABILITY_FIELDS[key]
            assert lo <= value <= hi, f"{key}={value} outside [{lo}, {hi}]"

    def test_descriptions_nonempty(self):
        for key, text in llm.RELIABILITY_DESCRIPTIONS.items():
            assert text.strip(), f"empty description for {key}"


class TestClamp:
    def test_clamps_above_and_below(self):
        out = settings._clamp_reliability({"timeout_s": 99999, "attempts": 0})
        assert out["timeout_s"] == llm.RELIABILITY_FIELDS["timeout_s"][1]
        assert out["attempts"] == llm.RELIABILITY_FIELDS["attempts"][0]

    def test_keeps_defaults_for_missing_values(self):
        out = settings._clamp_reliability({})
        assert out == llm.default_reliability()

    def test_rejects_non_numeric(self):
        with pytest.raises(HTTPException) as exc:
            settings._clamp_reliability({"deadline_s": "not-a-number"})
        assert exc.value.status_code == 422

    def test_ignores_unknown_fields(self):
        out = settings._clamp_reliability({"not_a_field": 123})
        assert "not_a_field" not in out

    def test_partial_merge_preserves_stored_values(self):
        stored = {"timeout_s": 30.0}
        merged = {**llm.default_reliability(), **stored}
        assert merged["timeout_s"] == 30.0
        assert merged["attempts"] == llm.default_reliability()["attempts"]
