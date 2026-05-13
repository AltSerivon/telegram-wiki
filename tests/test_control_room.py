from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from telegram_wiki import pipeline_runner
from telegram_wiki.db.models import CompanyGroup, WikiRun
from telegram_wiki.db.session import session_scope
from telegram_wiki.url_redact import redact_database_url


@pytest.fixture(autouse=True)
def reset_pipeline_state():
    pipeline_runner.reset_pipeline_state_for_tests()
    yield
    pipeline_runner.reset_pipeline_state_for_tests()


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
    assert "Run pipeline" in r.text
    assert "Database (redacted)" in r.text


def test_redact_database_url_unit():
    u = "postgresql://user:p%40ss%3Aword@localhost/db"
    out = redact_database_url(u)
    assert "p%40ss%3Aword" not in out
    assert ":***@" in out


def test_wiki_filter_failed(control_client: TestClient):
    with session_scope() as session:
        cg = CompanyGroup(name="Acme", slug="acme", vault_rel_path="_telegram_wiki/acme")
        session.add(cg)
        session.flush()
        session.add(
            WikiRun(
                company_group_id=cg.id,
                success=False,
                finished_at=datetime.utcnow(),
                error_message="unit-test-failure",
            )
        )
    r = control_client.get("/control?wiki_filter=failed")
    assert r.status_code == 200
    assert "unit-test-failure" in r.text
    r2 = control_client.get("/control?wiki_filter=unfinished")
    assert r2.status_code == 200
    assert "unit-test-failure" not in r2.text


def test_wiki_unfinished_stale_label(control_client: TestClient):
    with session_scope() as session:
        cg = CompanyGroup(name="Beta", slug="beta", vault_rel_path="_telegram_wiki/beta")
        session.add(cg)
        session.flush()
        old = datetime.utcnow() - timedelta(hours=5)
        session.add(
            WikiRun(
                company_group_id=cg.id,
                success=False,
                started_at=old,
                finished_at=None,
                error_message=None,
            )
        )
    r = control_client.get("/control?wiki_filter=unfinished")
    assert r.status_code == 200
    assert "incomplete" in r.text


def test_discover_action_schedules(control_client: TestClient, monkeypatch):
    calls: list[str] = []

    def fake_run_discover() -> str | None:
        calls.append("discover")
        return "ok"

    monkeypatch.setattr(pipeline_runner, "run_discover", fake_run_discover)
    r = control_client.post("/control/actions/discover", follow_redirects=False)
    assert r.status_code == 303
    assert "notice=started" in r.headers.get("location", "")
    assert calls == ["discover"]


def test_pipeline_busy_redirect(control_client: TestClient, monkeypatch):
    monkeypatch.setattr(pipeline_runner, "try_begin", lambda _kind: False)
    r = control_client.post("/control/actions/discover", follow_redirects=False)
    assert r.status_code == 303
    assert "error=busy" in r.headers.get("location", "")


def test_flash_busy_message(control_client: TestClient):
    r = control_client.get("/control?error=busy")
    assert r.status_code == 200
    assert "Another pipeline job" in r.text
