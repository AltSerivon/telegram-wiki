from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from telegram_wiki.db import init_db
from telegram_wiki.db.models import CompanyGroup
from telegram_wiki.db.session import session_scope
from telegram_wiki.utc import utc_now


@dataclass
class PipelineSnapshot:
    running: str | None
    last_finished_at: datetime | None
    last_job: str | None
    last_ok: bool | None
    last_message: str | None


_lock = threading.Lock()
_running: str | None = None
_last_finished_at: datetime | None = None
_last_job: str | None = None
_last_ok: bool | None = None
_last_message: str | None = None


def snapshot() -> PipelineSnapshot:
    with _lock:
        return PipelineSnapshot(
            running=_running,
            last_finished_at=_last_finished_at,
            last_job=_last_job,
            last_ok=_last_ok,
            last_message=_last_message,
        )


def try_begin(kind: str) -> bool:
    """Return True if this kind became the active pipeline job."""
    global _running
    with _lock:
        if _running is not None:
            return False
        _running = kind
        return True


def _finish(kind: str, ok: bool, message: str | None) -> None:
    global _running, _last_finished_at, _last_job, _last_ok, _last_message
    with _lock:
        _running = None
        _last_finished_at = utc_now()
        _last_job = kind
        _last_ok = ok
        _last_message = message


def run_guarded(kind: str, fn: Callable[[], str | None]) -> None:
    """Run a pipeline function; clears busy flag and records outcome. Intended for BackgroundTasks."""
    try:
        msg = fn()
        _finish(kind, True, msg)
    except Exception as exc:  # noqa: BLE001
        _finish(kind, False, str(exc)[:2000])


def run_discover() -> str | None:
    from telegram_wiki.ingest import discover_dialogs

    init_db()
    with session_scope() as session:
        n = asyncio.run(discover_dialogs(session))
    return f"Imported {n} dialogs."


def run_ingest(company_slug: str | None) -> str | None:
    from telegram_wiki.ingest import ingest_company

    init_db()
    with session_scope() as session:
        if company_slug:
            c = session.scalars(select(CompanyGroup).where(CompanyGroup.slug == company_slug)).first()
            if c is None:
                raise ValueError(f"Unknown company slug: {company_slug}")
            companies = [c]
        else:
            companies = list(session.scalars(select(CompanyGroup)).all())

    parts: list[str] = []
    for c in companies:
        cid = c.id

        async def _one(company_id: int = cid) -> dict:
            with session_scope() as session:
                cg = session.get(CompanyGroup, company_id)
                if cg is None:
                    return {}
                return await ingest_company(session, cg)

        r = asyncio.run(_one())
        slug = c.slug
        parts.append(f"{slug}: peers={r.get('peers')} messages={r.get('messages')} files={len(r.get('files') or [])}")
    return "; ".join(parts) if parts else "No company groups to ingest."


def run_wiki(company_slug: str | None) -> str | None:
    from telegram_wiki.wiki_llm import run_wiki_update

    init_db()
    with session_scope() as session:
        if company_slug:
            c = session.scalars(select(CompanyGroup).where(CompanyGroup.slug == company_slug)).first()
            if c is None:
                raise ValueError(f"Unknown company slug: {company_slug}")
            companies = [c]
        else:
            companies = list(session.scalars(select(CompanyGroup)).all())

    parts: list[str] = []
    for c in companies:
        with session_scope() as session:
            cg = session.get(CompanyGroup, c.id)
            if cg is None:
                continue
            wr = run_wiki_update(session, cg)
            parts.append(f"{cg.slug}: wiki_run id={wr.id} success={wr.success}")
    return "; ".join(parts) if parts else "No company groups for wiki update."


def reset_pipeline_state_for_tests() -> None:
    """Clear in-process pipeline flags (for isolated tests)."""
    global _running, _last_finished_at, _last_job, _last_ok, _last_message
    with _lock:
        _running = None
        _last_finished_at = None
        _last_job = None
        _last_ok = None
        _last_message = None


def run_daily(company_slug: str | None) -> str | None:
    from telegram_wiki.ingest import ingest_company
    from telegram_wiki.wiki_llm import run_wiki_update

    init_db()

    async def _ingest_company_id(company_id: int) -> dict:
        with session_scope() as session:
            cg = session.get(CompanyGroup, company_id)
            if cg is None:
                return {}
            return await ingest_company(session, cg)

    with session_scope() as session:
        if company_slug:
            companies = list(
                session.scalars(select(CompanyGroup).where(CompanyGroup.slug == company_slug)).all(),
            )
            if not companies:
                raise ValueError(f"Unknown company slug: {company_slug}")
        else:
            companies = list(session.scalars(select(CompanyGroup)).all())

    parts: list[str] = []
    for c in companies:
        r = asyncio.run(_ingest_company_id(c.id))
        with session_scope() as session:
            cg = session.get(CompanyGroup, c.id)
            if cg is None:
                continue
            wr = run_wiki_update(session, cg)
        parts.append(f"{c.slug}: ingest={r} wiki_success={wr.success}")
    return "; ".join(parts) if parts else "No company groups for daily run."
