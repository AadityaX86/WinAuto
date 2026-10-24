import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WINAUTO_HOME", str(tmp_path / "home"))
    yield


@pytest.fixture
def ctx(tmp_path):
    from winauto.adapters.storage.db import Database
    from winauto.config import Config
    from winauto.core.context import Context

    notes = []
    c = Context(config=Config(), db=Database(":memory:"), data_dir=tmp_path,
                notify=lambda t, m: notes.append((t, m)))
    c.notifications = notes  # type: ignore[attr-defined]
    return c
