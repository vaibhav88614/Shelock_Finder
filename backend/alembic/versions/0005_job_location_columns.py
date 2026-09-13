"""Add structured location columns to jobs.

Revision ID: 0005_job_location_columns
Revises: 0004_add_company_country
Create Date: 2026-08-31

Adds `city`, `region`, `country`, `is_remote` columns to jobs so the API can
build location facets (city / country / remote counts) instead of relying on
a substring match against the free-text `location` string.

The unstructured `location` column is preserved (it's what the CSV export and
the drawer both display verbatim). The parser populates the structured
columns at scrape time; a one-shot backfill re-parses every existing row.

Implementation notes
--------------------
Plain ``ALTER TABLE ADD COLUMN`` (SQLite 3.35+) is used instead of
``batch_alter_table`` — the batch flow recreates the table, which would
also destroy the FTS5 sync triggers wired up in migration 0002 and desync
the ``jobs_fts`` external-content mirror.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0005_job_location_columns"
down_revision = "0004_add_company_country"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("city", sa.String(128), nullable=True))
    op.add_column("jobs", sa.Column("region", sa.String(128), nullable=True))
    op.add_column("jobs", sa.Column("country", sa.String(64), nullable=True))
    op.add_column(
        "jobs",
        sa.Column(
            "is_remote",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_jobs_city", "jobs", ["city"])
    op.create_index("ix_jobs_country", "jobs", ["country"])
    op.create_index("ix_jobs_is_remote", "jobs", ["is_remote"])


def downgrade() -> None:
    op.drop_index("ix_jobs_is_remote", table_name="jobs")
    op.drop_index("ix_jobs_country", table_name="jobs")
    op.drop_index("ix_jobs_city", table_name="jobs")
    # Downgrade DOES require batch mode (SQLite lacks classic DROP COLUMN),
    # so we drop + recreate the FTS triggers around it.
    op.execute("DROP TRIGGER IF EXISTS jobs_au")
    op.execute("DROP TRIGGER IF EXISTS jobs_ad")
    op.execute("DROP TRIGGER IF EXISTS jobs_ai")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("is_remote")
        batch.drop_column("country")
        batch.drop_column("region")
        batch.drop_column("city")
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
