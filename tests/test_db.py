import db


def test_upsert_enriches_without_overwriting(data_dir):
    con = db.connect("crm")
    first = {"name": "Asha", "email_primary": "asha@x.com", "phone_primary": None,
             "company": "Acme"}
    cid, action = db.upsert_contact(con, first, "contacts")
    assert action == "new"

    second = {"name": "Asha R", "email_primary": "ASHA@x.com", "phone_primary": "9876543210",
              "company": "Other Co", "city": "Pune"}
    same_id, action = db.upsert_contact(con, second, "contacts")
    assert action == "merged"
    assert same_id == cid

    row = db.get_contact(con, "contacts", cid)
    assert row["name"] == "Asha"          # existing value kept
    assert row["company"] == "Acme"       # not overwritten
    assert row["phone_primary"] == "9876543210"  # gap filled
    assert row["city"] == "Pune"
    assert row["phone_key"] == "9876543210"


def test_phone_key_collapses_indian_prefixes():
    assert db.phone_key("+91 98765 43210") == "9876543210"
    assert db.phone_key("09876543210") == "9876543210"
    assert db.phone_key("9876543210") == "9876543210"


def test_dedup_index_matches_email_phone_and_name(data_dir):
    con = db.connect("eml")
    db.insert_eml_contact(con, 1, {
        "name": "Vikram Shah", "email_primary": "vikram@x.com",
        "phone_primary": "+91 98123 45678",
    }, "new", "a.eml")
    con.commit()

    index = db.DedupIndex.load(con, "eml_contacts", with_names=True)
    assert index.duplicate_reason("VIKRAM@x.com", None) == "email"
    assert index.duplicate_reason(None, "9812345678") == "phone"
    assert index.duplicate_reason(None, None, "vikram shah") == "name"
    assert index.duplicate_reason("new@x.com", "9000000000", "Someone Else") is None


def test_ledger_skips_only_when_size_and_mtime_match(data_dir):
    con = db.connect("crm")
    db.mark_processed(con, "/tmp/a.xlsx", 100, 1000.0, "ok", contacts_found=3)
    con.commit()
    assert db.is_processed(con, "/tmp/a.xlsx", 100, 1000.0)
    assert not db.is_processed(con, "/tmp/a.xlsx", 101, 1000.0)
    assert not db.is_processed(con, "/tmp/a.xlsx", 100, 1001.0)
