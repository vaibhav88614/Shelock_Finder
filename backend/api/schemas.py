"""Pydantic schemas for the HTTP API."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    careers_url: str
    ats_type: str
    ats_identifier: str | None = None
    custom_selectors: dict[str, Any] | None = None
    active: bool
    last_scraped_at: datetime | None = None
    last_success_at: datetime | None = None
    consecutive_failures: int = 0
    created_at: datetime

    @field_validator("custom_selectors", mode="before")
    @classmethod
    def _parse_selectors(cls, v):  # noqa: ANN001
        if v is None or isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return None
        return None


class CompanyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    careers_url: HttpUrl
    ats_type: str | None = None  # auto-detect when omitted (phase 6)
    ats_identifier: str | None = None
    custom_selectors: dict[str, Any] | None = None
    active: bool = True


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    careers_url: HttpUrl | None = None
    ats_type: str | None = None
    ats_identifier: str | None = None
    custom_selectors: dict[str, Any] | None = None
    active: bool | None = None


class CompanyBulkImportRow(BaseModel):
    name: str
    careers_url: str


class CompanyBulkImportResult(BaseModel):
    inserted: int
    updated: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class CompanyBulkActiveIn(BaseModel):
    """Body for `POST /companies/bulk-active` — flip .active on many rows.

    Either supply an explicit `ids` list or (when the caller wants "everything
    matching a health predicate") an `ats_types` allowlist plus
    `max_consecutive_failures`.
    """
    active: bool
    ids: list[int] | None = None
    ats_types: list[str] | None = None
    max_consecutive_failures: int | None = None


class CompanyBulkActiveResult(BaseModel):
    updated: int
    matched: int


class CleanupJobsResult(BaseModel):
    cutoff: datetime
    matched: int
    deleted: int
    dry_run: bool


class DetectAtsOut(BaseModel):
    """Lightweight URL → ATS classification result for the Add-Company UI."""
    ats_type: str | None = None
    ats_identifier: str | None = None
    recognized: bool


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    company_name: str | None = None
    title: str
    location: str | None = None
    remote_type: str | None = None
    department: str | None = None
    employment_type: str | None = None
    experience_min: int | None = None
    experience_max: int | None = None
    posted_date: datetime | None = None
    apply_url: str
    description: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    is_active: bool
    keywords_matched: list[str] = Field(default_factory=list)


class JobsListOut(BaseModel):
    items: list[JobOut]
    next_cursor: str | None = None
    total: int | None = None


# ---------------------------------------------------------------------------
# Scrape runs / stats
# ---------------------------------------------------------------------------


class ScrapeRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    companies_scraped: int
    jobs_found_total: int
    jobs_new_total: int
    error_summary: str | None = None


class CompanyHealth(BaseModel):
    id: int
    name: str
    ats_type: str
    active: bool
    # True when the company is driven by CSS selectors (ats_type custom /
    # playwright) and those selectors are configured — i.e. a "custom-selector
    # company" whose scraping the admin UI can toggle on/off.
    has_selectors: bool = False
    last_scraped_at: datetime | None
    last_success_at: datetime | None
    consecutive_failures: int
    jobs_active: int


class StatsOut(BaseModel):
    jobs_total: int
    jobs_active: int
    jobs_last_15d: int
    companies_total: int
    companies_active: int
    last_run: ScrapeRunOut | None = None


# ---------------------------------------------------------------------------
# Filter inputs
# ---------------------------------------------------------------------------

SortOption = Literal["posted_date", "company", "title", "first_seen"]
KeywordLogic = Literal["and", "or"]
