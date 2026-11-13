# tests/test_dedup_rules.py
from services.keys import normalize_email, phone_key


def test_normalize_email():
    assert normalize_email("  Test@Example.COM  ") == "test@example.com"
    assert normalize_email(None) == ""
    assert normalize_email("") == ""


def test_phone_key_collapses_indian_prefixes():
    assert phone_key("+91 98765 43210") == "9876543210"
    assert phone_key("09876543210") == "9876543210"
    assert phone_key("9876543210") == "9876543210"
    assert phone_key(None) is None
    assert phone_key("123") is None



def test_is_duplicate_email():
    from services.keys import is_duplicate
    existing_emails = {"test@example.com"}
    existing_phones = set()
    assert is_duplicate("test@example.com", None, existing_emails, existing_phones) == "email"
    assert is_duplicate("new@example.com", None, existing_emails, existing_phones) is None