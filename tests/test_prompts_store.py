# tests/test_prompts_store.py — two-prompt store: defaults, save isolation,
# validation, reset (Part 4 of the provider-reliability work).
import json

import config
import services.prompts.store as store
from services.prompts.contact_extraction import MASTER_SYSTEM_PROMPT

KINDS = ("contact", "eml")


def _stored_prompts(cfg_path):
    return json.loads(cfg_path.read_text()).get("prompts") or {}


def _cfg_path(data_dir):
    return data_dir / "config.json"


def test_default_eml_prompt_is_self_contained_and_contract_shaped():
    """The EML prompt must be usable standalone and keep the 10-field contract."""
    import llm
    text = store.default_text("eml")
    assert text.count('"name":null') >= 1
    for field in ("name", "email", "phone_primary", "phone_secondary", "company",
                  "designation", "address", "city", "pincode", "website"):
        assert field in text
    # llm.SYSTEM_PROMPT delegates to the store default (single source of truth)
    assert llm._default_eml_prompt() == text


def test_default_contact_extends_master_prompt():
    d = store.default_text("contact")
    assert d.startswith(MASTER_SYSTEM_PROMPT)
    assert "UNTRUSTED" in d


def test_text_falls_back_to_default_without_edit(data_dir):
    for k in KINDS:
        assert store.text(k) == store.default_text(k)


def test_save_persists_only_that_kind(data_dir):
    assert store.save("eml", store.default_text("eml").replace(
        "HOW TO READ THE EMAIL", "HOW TO READ THE EMAIL (edited)"))
    prompts = _stored_prompts(_cfg_path(data_dir))
    assert set(prompts) == {"eml"}  # saving one kind never creates the other
    assert "(edited)" in prompts["eml"]["text"]
    assert prompts["eml"]["default_version"] == store.DEFAULT_VERSION
    assert prompts["eml"]["updated_at"]
    # config.json stays 0600 on POSIX (SEC-09); Windows inherits the
    # user-profile ACL and os.chmod cannot express owner-only there.
    import os, stat
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(_cfg_path(data_dir)).st_mode) == 0o600


def test_save_rejects_empty_and_unknown_kind(data_dir):
    ok, why = store.save("eml", "   \n  ")
    assert not ok and "empty" in why
    ok, why = store.save("nope", "x")
    assert not ok and "unknown" in why
    # rejected saves must not create prompts storage or change config
    cfg_path = _cfg_path(data_dir)
    if cfg_path.exists():
        assert not _stored_prompts(cfg_path)


def test_validation_rejects_missing_contract_markers(data_dir):
    bad_eml = "Extract contacts. Return JSON."
    ok, why = store.validator("eml", bad_eml)
    assert not ok and "pincode" in why and "website" in why

    bad_contact = "You are an extraction assistant."
    ok, why = store.validator("contact", bad_contact)
    assert not ok and "schema_version" in why and "field_evidence" in why

    ok, why = store.validator("contact", MASTER_SYSTEM_PROMPT)
    assert not ok  # dogfooding: MASTER alone lacks contract words; default adds them
    ok, why = store.validator("contact", store.default_text("contact"))
    assert ok and why == ""


def test_every_default_passes_its_own_validator():
    for k in KINDS:
        ok, why = store.validator(k, store.default_text(k))
        assert ok and why == "", k


def test_reset_restores_default_without_touching_other_kind(data_dir):
    custom = "custom " + store.default_text("eml")
    assert store.save("eml", custom)
    before_contact = store.load("contact")
    assert store.reset("eml")
    assert store.text("eml") == store.default_text("eml")
    assert store.load("contact") == before_contact  # untouched
    assert _stored_prompts(_cfg_path(data_dir)) == {}


def test_saved_prompt_survives_reload_via_config(data_dir):
    # Simulate app restart: config file is read fresh by store.load/text.
    edited = store.default_text("eml").replace("Never invent values.",
                                               "Never invent values. Extract city when present.")
    assert store.save("eml", edited)
    assert config.load()["prompts"]["eml"]["text"] == edited
    assert store.text("eml") == edited


def test_missing_metadata_is_tolerated(data_dir):
    # Old configs may lack the "prompts" key entirely.
    cfg_path = _cfg_path(data_dir)
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    cfg.pop("prompts", None)
    cfg_path.write_text(json.dumps(cfg))
    assert store.text("contact") == store.default_text("contact")
