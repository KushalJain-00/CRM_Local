# tests/test_app.py — App endpoint tests
import pytest
from fastapi.testclient import TestClient
from app import app
import db  # noqa: E402 - needed for db.init() in fixture

client = TestClient(app)


@pytest.fixture(autouse=True)
def ensure_db_initialized():
    """Ensure the database is initialized before each test.
    
    The FastAPI lifespan calls db.init(), but only when TestClient is used
    as a context manager. This fixture guarantees initialization for tests
    that don't use the context manager directly.
    """
    # The TestClient without context manager doesn't trigger lifespan,
    # so we init here to ensure the database exists.
    db.init()
    return None


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
    assert r.status_code == 410


def test_contacts_list():
    # D-032 Q2: `which` param dropped outright; route implemented in the
    # integration-repair campaign — contract is {rows, total, page, pageSize}.
    r = client.get("/api/contacts?which=crm")
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body and "total" in body


def test_contacts_invalid_which():
    # D-032 Q2: `which` param is dropped outright, not validated — unknown
    # query params are ignored, the route still answers 200.
    r = client.get("/api/contacts?which=invalid")
    assert r.status_code == 200


def test_pick_folder():
    r = client.post("/api/pick-folder", json={"initial": ""})
    assert r.status_code == 200


def test_settings_get():
    r = client.get("/api/settings")
    assert r.status_code == 200
