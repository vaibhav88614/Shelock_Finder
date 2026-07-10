"""Add nullable `country` column to companies.

Revision ID: 0004_add_company_country
Revises: 0003_cursor_and_finalize_indexes
Create Date: 2026-07-10

Adds `companies.country` (nullable) plus an index. This is an internal signal
used by the scrape pipeline to normalize per-job location strings (see
`backend/scrape.py` `_enrich_location`) so the existing free-text Location
filter reliably matches jobs from companies tagged with a country (e.g.
"India"). It is NOT exposed as an API query param or a dashboard filter.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0004_add_company_country"
down_revision = "0003_cursor_and_finalize_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("country", sa.String(64), nullable=True))
    op.create_index("ix_companies_country", "companies", ["country"])


def downgrade() -> None:
    op.drop_index("ix_companies_country", table_name="companies")
    # Batch mode so SQLite (which lacks a first-class DROP COLUMN on older
    # engines) rebuilds the table cleanly.
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("country")
