"""FTS5 virtual table for job search + sync triggers

Revision ID: 0002_fts5_jobs
Revises: 0001_initial
Create Date: 2026-05-23
"""
from __future__ import annotations

from alembic import op


revision = "0002_fts5_jobs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # External-content FTS5 table backed by the `jobs` table.
    op.execute(
        """
        CREATE VIRTUAL TABLE jobs_fts USING fts5(
            title,
            description,
            content='jobs',
            content_rowid='id',
            tokenize='porter unicode61'
        )
        """
    )
    # Keep FTS5 in sync with the base table.
    op.execute(
        """
        CREATE TRIGGER jobs_ai AFTER INSERT ON jobs BEGIN
            INSERT INTO jobs_fts(rowid, title, description)
            VALUES (new.id, new.title, COALESCE(new.description, ''));
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER jobs_ad AFTER DELETE ON jobs BEGIN
            INSERT INTO jobs_fts(jobs_fts, rowid, title, description)
            VALUES('delete', old.id, old.title, COALESCE(old.description, ''));
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER jobs_au AFTER UPDATE ON jobs BEGIN
            INSERT INTO jobs_fts(jobs_fts, rowid, title, description)
            VALUES('delete', old.id, old.title, COALESCE(old.description, ''));
            INSERT INTO jobs_fts(rowid, title, description)
            VALUES (new.id, new.title, COALESCE(new.description, ''));
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS jobs_au")
    op.execute("DROP TRIGGER IF EXISTS jobs_ad")
    op.execute("DROP TRIGGER IF EXISTS jobs_ai")
    op.execute("DROP TABLE IF EXISTS jobs_fts")
