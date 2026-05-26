"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("careers_url", sa.String(1024), nullable=False),
        sa.Column("ats_type", sa.String(64), nullable=False, server_default="custom"),
        sa.Column("ats_identifier", sa.String(255), nullable=True),
        sa.Column("custom_selectors", sa.Text, nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("last_scraped_at", sa.DateTime, nullable=True),
        sa.Column("last_success_at", sa.DateTime, nullable=True),
        sa.Column("consecutive_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index("ix_companies_ats_type", "companies", ["ats_type"])
    op.create_index("ix_companies_active", "companies", ["active"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("location", sa.String(512), nullable=True),
        sa.Column("remote_type", sa.String(64), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("employment_type", sa.String(64), nullable=True),
        sa.Column("experience_min", sa.Integer, nullable=True),
        sa.Column("experience_max", sa.Integer, nullable=True),
        sa.Column("posted_date", sa.DateTime, nullable=True),
        sa.Column("apply_url", sa.String(1024), nullable=False),
        sa.Column("raw_payload", sa.Text, nullable=True),
        sa.Column("first_seen_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("last_seen_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.UniqueConstraint("fingerprint", name="uq_jobs_fingerprint"),
    )
    op.create_index("ix_jobs_posted_date", "jobs", ["posted_date"])
    op.create_index("ix_jobs_company_posted", "jobs", ["company_id", "posted_date"])
    op.create_index("ix_jobs_first_seen_at", "jobs", ["first_seen_at"])
    op.create_index("ix_jobs_is_active", "jobs", ["is_active"])

    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("started_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("finished_at", sa.DateTime, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("companies_scraped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("jobs_found_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("jobs_new_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text, nullable=True),
    )
    op.create_index("ix_scrape_runs_started_at", "scrape_runs", ["started_at"])

    op.create_table(
        "scrape_run_companies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("scrape_run_id", sa.Integer, sa.ForeignKey("scrape_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("jobs_found", sa.Integer, nullable=False, server_default="0"),
        sa.Column("jobs_new", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.create_index("ix_src_run_company", "scrape_run_companies", ["scrape_run_id", "company_id"])


def downgrade() -> None:
    op.drop_index("ix_src_run_company", table_name="scrape_run_companies")
    op.drop_table("scrape_run_companies")
    op.drop_index("ix_scrape_runs_started_at", table_name="scrape_runs")
    op.drop_table("scrape_runs")
    op.drop_index("ix_jobs_is_active", table_name="jobs")
    op.drop_index("ix_jobs_first_seen_at", table_name="jobs")
    op.drop_index("ix_jobs_company_posted", table_name="jobs")
    op.drop_index("ix_jobs_posted_date", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_companies_active", table_name="companies")
    op.drop_index("ix_companies_ats_type", table_name="companies")
    op.drop_table("companies")
