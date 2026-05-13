from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def control_client(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_ID", "12345678")
    monkeypatch.setenv("TELEGRAM_API_HASH", "test_hash_value")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import telegram_wiki.db.session as db_session

    db_session._engine = None
    db_session._SessionLocal = None

    from telegram_wiki.db import init_db

    init_db()

    from telegram_wiki.app import create_app

    return TestClient(create_app())


def test_control_room_ok(control_client: TestClient):
    r = control_client.get("/control")
    assert r.status_code == 200
    assert "Control room" in r.text
    assert "Recent wiki runs" in r.text
