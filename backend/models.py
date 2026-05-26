"""SQLAlchemy ORM models for JobPulse.

Schema mirrors the spec in section 4 of the build prompt:
  - companies
  - jobs (with UNIQUE fingerprint, indexes for dashboard queries)
  - scrape_runs
  - scrape_run_companies

Notes:
  * Timestamps stored as naive UTC `datetime` (SQLite has no native tz).
  * JSON blobs stored as TEXT (SQLite JSON1 functions work fine on TEXT).
  * The FTS5 virtual table for `jobs` is created in Alembic migration 0002,
    not as an ORM model (SQLAlchemy can't reflect FTS5 cleanly).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.utcnow()


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    careers_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    ats_type: Mapped[str] = mapped_column(String(64), nullable=False, default="custom")
    ats_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # JSON-encoded CSS selector spec for CustomAdapter / Playwright fallback.
    custom_selectors: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    jobs: Mapped[list["Job"]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_companies_ats_type", "ats_type"),
        Index("ix_companies_active", "active"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    remote_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    experience_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    experience_max: Mapped[int | None] = mapped_column(Integer, nullable=True)

    posted_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    apply_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    company: Mapped[Company] = relationship(back_populates="jobs")

    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_jobs_fingerprint"),
        Index("ix_jobs_posted_date", "posted_date"),
        Index("ix_jobs_company_posted", "company_id", "posted_date"),
        Index("ix_jobs_first_seen_at", "first_seen_at"),
        Index("ix_jobs_is_active", "is_active"),
    )


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    companies_scraped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_found_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_new_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    company_runs: Mapped[list["ScrapeRunCompany"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (Index("ix_scrape_runs_started_at", "started_at"),)


class ScrapeRunCompany(Base):
    __tablename__ = "scrape_run_companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scrape_run_id: Mapped[int] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    jobs_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[ScrapeRun] = relationship(back_populates="company_runs")

    __table_args__ = (
        Index("ix_src_run_company", "scrape_run_id", "company_id"),
    )
