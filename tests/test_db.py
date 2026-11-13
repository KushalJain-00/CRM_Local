import db

from services.keys import phone_key



def test_phone_key_collapses_indian_prefixes():
    assert phone_key("+91 98765 43210") == "9876543210"
    assert phone_key("09876543210") == "9876543210"
    assert phone_key("9876543210") == "9876543210"



def test_ledger_skips_only_when_size_and_mtime_match(data_dir):
    con = db.connect("crm")
    db.mark_processed(con, "/tmp/a.xlsx", 100, 1000.0, "ok", contacts_found=3)
    con.commit()
    assert db.is_processed(con, "/tmp/a.xlsx", 100, 1000.0)
    assert not db.is_processed(con, "/tmp/a.xlsx", 101, 1000.0)
    assert not db.is_processed(con, "/tmp/a.xlsx", 100, 1001.0)
