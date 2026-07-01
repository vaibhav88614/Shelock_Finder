"""Composite indexes for cursor pagination + finalize-run UPDATE/DELETE.

Revision ID: 0003_cursor_and_finalize_indexes
Revises: 0002_fts5_jobs
Create Date: 2026-07-01

- `ix_jobs_posted_date_id_desc` matches `ORDER BY posted_date DESC, id DESC`
  used by `build_jobs_query` for the default `sort=posted_date` keyset.
- `ix_jobs_first_seen_id_desc` matches `ORDER BY first_seen_at DESC, id DESC`
  for `sort=first_seen`.
- `ix_jobs_company_last_seen` matches the inactive-mark `UPDATE` and the
  retention `DELETE` in `_finalize_run` (Phase 1.1).
"""
from __future__ import annotations

from alembic import op


revision = "0003_cursor_and_finalize_indexes"
down_revision = "0002_fts5_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Descending key order matters: SQLite can satisfy ORDER BY without a sort
    # step only when the index direction matches the query direction.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_posted_date_id_desc "
        "ON jobs (posted_date DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_first_seen_id_desc "
        "ON jobs (first_seen_at DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_company_last_seen "
        "ON jobs (company_id, last_seen_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_company_last_seen")
    op.execute("DROP INDEX IF EXISTS ix_jobs_first_seen_id_desc")
    op.execute("DROP INDEX IF EXISTS ix_jobs_posted_date_id_desc")
