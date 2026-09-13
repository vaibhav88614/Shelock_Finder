"""Resume storage + cached job-match scores.

Revision ID: 0006_resume_and_matches
Revises: 0005_job_location_columns
Create Date: 2026-08-31

Two new tables:

    resumes
        Singleton-in-practice (the UI only exposes one active resume) but
        modeled as a table so multiple profiles can be tracked later. Stores
        the plain-text extract + a JSON blob of the tokenised bag-of-words
        the scorer uses.

    job_matches
        Cached BM25 score of one (job, resume) pair. Populated at upload
        time (all jobs) and after every scrape run (delta). Indexed on
        `(resume_id, score)` so `sort=match` is a cheap desc scan.

Both tables cascade on their parents (companies drop → jobs drop → matches
drop; resumes drop → matches drop) so cleanup + prune stay consistent.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0006_resume_and_matches"
down_revision = "0005_job_location_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resumes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("tokens", sa.Text, nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("uploaded_at", sa.DateTime, nullable=False),
        sa.Column("scored_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_resumes_is_active", "resumes", ["is_active"])

    op.create_table(
        "job_matches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "resume_id",
            sa.Integer,
            sa.ForeignKey("resumes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Integer,
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Float, nullable=False, server_default="0"),
        # Comma-separated terms that contributed to the score. Kept short so
        # SQLite pages stay dense; the UI only shows the top-10 anyway.
        sa.Column("matched_terms", sa.String(512), nullable=True),
        sa.Column("computed_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("resume_id", "job_id", name="uq_job_matches_resume_job"),
    )
    op.create_index(
        "ix_job_matches_resume_score",
        "job_matches",
        ["resume_id", "score"],
    )
    op.create_index(
        "ix_job_matches_job",
        "job_matches",
        ["job_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_matches_job", table_name="job_matches")
    op.drop_index("ix_job_matches_resume_score", table_name="job_matches")
    op.drop_table("job_matches")
    op.drop_index("ix_resumes_is_active", table_name="resumes")
    op.drop_table("resumes")
