# tests/test_adapters.py — Adapter tests for CRM_Local
import os
import tempfile
import asyncio
import pytest

from services.adapters import get_adapter, dispatch, NormalizedContact, ExtractionResult


def test_dispatch_xlsx():
    assert dispatch("test.xlsx") == "xlsx"


def test_dispatch_xls():
    assert dispatch("test.xls") == "xls"


def test_dispatch_csv():
    assert dispatch("test.csv") == "csv"


def test_dispatch_pdf():
    assert dispatch("test.pdf") == "pdf"


def test_dispatch_txt():
    assert dispatch("test.txt") == "txt"


def test_dispatch_eml():
    assert dispatch("test.eml") == "eml"


def test_dispatch_unknown():
    assert dispatch("test.xyz") == "unknown"


def test_get_adapter_returns_none_for_unknown():
    assert get_adapter("test.xyz") is None


def test_normalized_contact_defaults():
    nc = NormalizedContact()
    assert nc.name is None
    assert nc.email_primary is None
    assert nc.confidence == 0.0


def test_extraction_result_defaults():
    er = ExtractionResult()
    assert er.contacts == []
    assert er.warnings == []
    assert er.adapter == ""


@pytest.mark.asyncio
async def test_txt_adapter_empty_file():
    adapter = get_adapter("test.txt")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("")
        path = f.name
    try:
        result = await adapter.extract(path)
        assert result.adapter == "txt"
        assert result.contacts == []
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_txt_adapter_with_phones():
    adapter = get_adapter("test.txt")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Contact: John Doe\nPhone: 9876543210\n")
        path = f.name
    try:
        result = await adapter.extract(path)
        assert result.adapter == "txt"
        assert len(result.contacts) == 1
        assert result.contacts[0].phone_primary == "9876543210"
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_csv_adapter_basic():
    adapter = get_adapter("test.csv")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
        f.write("Name,Email,Phone,Company\n")
        f.write("John Doe,john@acme.com,9876543210,Acme Ltd\n")
        path = f.name
    try:
        result = await adapter.extract(path)
        assert result.adapter == "csv"
        assert len(result.contacts) == 1
        assert result.contacts[0].name == "John Doe"
        assert result.contacts[0].email_primary == "john@acme.com"
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_eml_adapter_basic():
    adapter = get_adapter("test.eml")
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".eml", delete=False) as f:
        f.write(b"From: John Doe <john@acme.com>\r\nTo: sales@x.com\r\nSubject: Hi\r\n\r\n-- \r\nJohn Doe\r\nManager\r\n+91 98765 43210\r\n")
        path = f.name
    try:
        result = await adapter.extract(path)
        assert result.adapter == "eml"
        assert len(result.contacts) == 1
        assert result.contacts[0].name == "John Doe"
        assert result.contacts[0].email_primary == "john@acme.com"
    finally:
        os.unlink(path)