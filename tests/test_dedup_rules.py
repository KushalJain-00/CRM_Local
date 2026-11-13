# tests/test_dedup_rules.py
import db

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


def test_dedup_index_load_and_match(data_dir):
    con = db.connect("crm")
    # Insert a contact
    db.upsert_contact(con, {"name": "Test User", "email_primary": "test@x.com", "phone_primary": "9876543210"}, "contacts")
    con.commit()
    index = db.DedupIndex.load(con, "contacts", with_names=True)
    assert index.duplicate_reason("test@x.com", None) == "email"
    assert index.duplicate_reason(None, "9876543210") == "phone"
    assert index.duplicate_reason(None, None, "test user") == "name"
    assert index.duplicate_reason("new@x.com", "9000000000", "Someone Else") is None
    con.close()


def test_is_duplicate_email():
    from services.keys import is_duplicate
    existing_emails = {"test@example.com"}
    existing_phones = set()
    assert is_duplicate("test@example.com", None, existing_emails, existing_phones) == "email"
    assert is_duplicate("new@example.com", None, existing_emails, existing_phones) is None