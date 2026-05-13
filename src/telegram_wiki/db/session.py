from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from telegram_wiki.config import get_settings


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite:///"):
        path = url.removeprefix("sqlite:///")
        if path != ":memory:" and not path.startswith("sqlite://"):
            p = Path(path).parent
            if p.parts:
                p.mkdir(parents=True, exist_ok=True)


_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        s = get_settings()
        _ensure_sqlite_dir(s.database_url)
        connect_args = {}
        if s.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(s.database_url, connect_args=connect_args)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_session_factory():
    get_engine()
    return _SessionLocal


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
