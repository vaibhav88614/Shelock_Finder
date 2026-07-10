"""Alembic migration idempotency + FTS5 schema/triggers integration.

Covers the Phase 2.4 idempotency guards on `0002_fts5_jobs.py` and validates
that the FTS5 virtual table + sync triggers actually work end-to-end after
migration: an inserted job appears in `jobs_fts MATCH` results.

This file does NOT use the `api_env` fixture because we need a fully fresh DB
for clean migration semantics (no `upgrade_to_head` already called).
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from sqlalchemy import text


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Bind the backend to an empty SQLite at tmp_path/mig.db, no migrations applied."""
    from backend import config, db

    db_path: Path = tmp_path / "mig.db"
    new_settings = dataclasses.replace(
        config.settings,
        db_path=db_path,
        data_dir=tmp_path,
    )
    monkeypatch.setattr(config, "settings", new_settings)
    db.rebind(new_settings.db_url)
    yield new_settings
    db.engine.dispose()


def test_upgrade_to_head_is_idempotent(fresh_db):
    """Calling `upgrade_to_head` twice must succeed (Phase 2.4)."""
    from backend.migrations import upgrade_to_head

    upgrade_to_head()
    # Re-run; Alembic should detect head and the FTS5 guard should prevent
    # `CREATE VIRTUAL TABLE` from firing a second time.
    upgrade_to_head()


def test_fts5_table_and_triggers_present_after_upgrade(fresh_db):
    """All four FTS5 objects exist post-migration."""
    from backend.db import engine
    from backend.migrations import upgrade_to_head

    upgrade_to_head()
    with engine.connect() as conn:
        names = {
            r[0]
            for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE name LIKE 'jobs%'")
            ).all()
        }
    assert "jobs" in names
    assert "jobs_fts" in names
    assert "jobs_ai" in names
    assert "jobs_ad" in names
    assert "jobs_au" in names


def test_fts5_insert_trigger_syncs_new_row(fresh_db):
    """Insert a Job and verify the row appears in `jobs_fts` via the trigger."""
    from backend.db import engine, session_scope
    from backend.migrations import upgrade_to_head
    from backend.models import Company, Job, utcnow_naive

    upgrade_to_head()
    with session_scope() as s:
        c = Company(
            name="A", careers_url="https://x.example/jobs",
            ats_type="custom", active=True,
        )
        s.add(c)
        s.flush()
        now = utcnow_naive()
        s.add(
            Job(
                company_id=c.id,
                external_id="1",
                fingerprint="a" * 64,
                title="Senior Python Engineer",
                description="Build FastAPI backends.",
                apply_url="https://x.example/jobs/1",
                first_seen_at=now,
                last_seen_at=now,
                is_active=True,
            )
        )

    with engine.connect() as conn:
        hits = conn.execute(
            text("SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH 'python'")
        ).fetchall()
    assert len(hits) == 1


def test_fts5_delete_trigger_removes_row(fresh_db):
    """Deleting a Job must remove it from FTS5 results."""
    from backend.db import engine, session_scope
    from backend.migrations import upgrade_to_head
    from backend.models import Company, Job, utcnow_naive

    upgrade_to_head()
    with session_scope() as s:
        c = Company(
            name="A", careers_url="https://x.example/jobs",
            ats_type="custom", active=True,
        )
        s.add(c)
        s.flush()
        now = utcnow_naive()
        j = Job(
            company_id=c.id,
            external_id="1",
            fingerprint="b" * 64,
            title="Unique RustomFoo Engineer",
            apply_url="https://x.example/jobs/1",
            first_seen_at=now,
            last_seen_at=now,
            is_active=True,
        )
        s.add(j)
        s.flush()
        job_id = j.id

    with engine.connect() as conn:
        before = conn.execute(
            text("SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH 'RustomFoo'")
        ).fetchall()
    assert len(before) == 1

    with session_scope() as s:
        j = s.get(Job, job_id)
        s.delete(j)

    with engine.connect() as conn:
        after = conn.execute(
            text("SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH 'RustomFoo'")
        ).fetchall()
    assert len(after) == 0


def test_country_column_present_after_upgrade(fresh_db):
    """Migration 0004 adds `companies.country` (nullable) plus its index."""
    from backend.db import engine
    from backend.migrations import upgrade_to_head

    upgrade_to_head()
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(companies)")).all()}
        idx = {r[1] for r in conn.execute(text("PRAGMA index_list(companies)")).all()}
    assert "country" in cols
    assert "ix_companies_country" in idx


def test_country_column_absent_after_downgrade_one(fresh_db):
    """Downgrading only 0004 removes the country column (and its index)."""
    from alembic import command

    from backend.db import engine
    from backend.migrations import _alembic_cfg, upgrade_to_head

    upgrade_to_head()
    # Step 0004 -> 0003 specifically.
    command.downgrade(_alembic_cfg(), "0003_cursor_and_finalize_indexes")
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(companies)")).all()}
        idx = {r[1] for r in conn.execute(text("PRAGMA index_list(companies)")).all()}
    assert "country" not in cols
    assert "ix_companies_country" not in idx


def test_country_roundtrips_through_orm(fresh_db):
    """A Company row can persist and read back a country value."""
    from backend.db import session_scope
    from backend.migrations import upgrade_to_head
    from backend.models import Company

    upgrade_to_head()
    with session_scope() as s:
        s.add(Company(name="IndiaCo", careers_url="https://x/careers",
                      ats_type="custom", country="India", active=True))
    with session_scope() as s:
        from sqlalchemy import select

        c = s.scalar(select(Company).where(Company.name == "IndiaCo"))
        assert c is not None
        assert c.country == "India"


def test_downgrade_and_reupgrade(fresh_db):
    """downgrade_to_base drops the schema; re-upgrading must rebuild it."""
    from backend.db import engine
    from backend.migrations import downgrade_to_base, upgrade_to_head

    upgrade_to_head()
    downgrade_to_base()
    with engine.connect() as conn:
        names = {
            r[0]
            for r in conn.execute(text("SELECT name FROM sqlite_master")).all()
        }
    assert "jobs" not in names
    assert "jobs_fts" not in names
    assert "companies" not in names

    upgrade_to_head()
    with engine.connect() as conn:
        names = {
            r[0]
            for r in conn.execute(text("SELECT name FROM sqlite_master")).all()
        }
    assert "jobs" in names
    assert "jobs_fts" in names
