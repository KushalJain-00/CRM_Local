# tests/test_app.py — App endpoint tests
import pytest
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


def test_index():
    r = client.get("/")
    assert r.status_code == 200


def test_status():
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert "counts" in body
    assert "version" in body


def test_config_get():
    r = client.get("/api/config")
    assert r.status_code == 200


def test_contacts_list():
    r = client.get("/api/contacts?which=crm")
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body
    assert "total" in body


def test_contacts_invalid_which():
    r = client.get("/api/contacts?which=invalid")
    assert r.status_code == 400


def test_pick_folder():
    r = client.post("/api/pick-folder", json={"initial": ""})
    assert r.status_code == 200


def test_settings_get():
    r = client.get("/api/settings")
    assert r.status_code == 200