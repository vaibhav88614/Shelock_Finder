"""SQLite engine + session factory.

- File-based SQLite at `data/jobpulse.db`.
- WAL mode enabled at connect-time for concurrent reads while the scraper writes.
- `foreign_keys` enforced (SQLite requires opting in per connection).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings


def _make_engine() -> Engine:
    engine = create_engine(
        settings.db_url,
        future=True,
        # check_same_thread=False so FastAPI threadpool can share connections.
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _conn_record):  # type: ignore[no-untyped-def]
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")  # 30s
            cur.execute("PRAGMA temp_store=MEMORY")
        finally:
            cur.close()

    return engine


engine: Engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def rebind(db_url: str) -> None:
    """Re-point engine + SessionLocal at a new SQLite URL. Test-only helper.

    Disposes the previous engine. The module-level `engine` is reassigned and
    `SessionLocal` is re-configured in place so any code that already imported
    it picks up the new bind.
    """
    global engine
    from sqlalchemy import create_engine as _create

    engine.dispose()
    new_engine = _create(
        db_url,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(new_engine, "connect")
    def _on_connect(dbapi_conn, _conn_record):  # type: ignore[no-untyped-def]
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")
        finally:
            cur.close()

    engine = new_engine
    SessionLocal.configure(bind=engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope helper for scripts."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a Session."""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
