import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    target = tmp_path / "data"
    target.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: target)
    import db
    db.init()
    return target
