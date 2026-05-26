"""/api/v1/jobs and /api/v1/jobs/export.csv routes."""
from __future__ import annotations

import csv
from datetime import datetime
from io import StringIO
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Company, Job
from .filters import (
    JobFilters,
    build_jobs_query,
    cursor_for_row,
    matched_keywords,
)
from .schemas import JobOut, JobsListOut


router = APIRouter(prefix="/jobs", tags=["jobs"])


def _filters_from_query(
    company_ids: list[int] | None,
    keywords: list[str] | None,
    keyword_logic: str,
    experience_min: int | None,
    experience_max: int | None,
    posted_within_days: int,
    location: str | None,
    remote_only: bool | None,
    sort: str,
    new_since: datetime | None,
    new_in_last_run: bool,
) -> JobFilters:
    return JobFilters(
        company_ids=company_ids or None,
        keywords=keywords or None,
        keyword_logic=keyword_logic,
        experience_min=experience_min,
        experience_max=experience_max,
        posted_within_days=posted_within_days,
        location=location,
        remote_only=remote_only,
        sort=sort,
        new_since=new_since,
        new_in_last_run=new_in_last_run,
    )


def _to_job_out(job: Job, company_name: str, keywords: list[str] | None) -> JobOut:
    return JobOut(
        id=job.id,
        company_id=job.company_id,
        company_name=company_name,
        title=job.title,
        location=job.location,
        remote_type=job.remote_type,
        department=job.department,
        employment_type=job.employment_type,
        experience_min=job.experience_min,
        experience_max=job.experience_max,
        posted_date=job.posted_date,
        apply_url=job.apply_url,
        description=job.description,
        first_seen_at=job.first_seen_at,
        last_seen_at=job.last_seen_at,
        is_active=job.is_active,
        keywords_matched=matched_keywords(job, keywords),
    )


@router.get("", response_model=JobsListOut)
def list_jobs(
    company_ids: list[int] | None = Query(default=None),
    keywords: list[str] | None = Query(default=None),
    keyword_logic: str = Query(default="or", pattern="^(and|or)$"),
    experience_min: int | None = Query(default=None, ge=0, le=30),
    experience_max: int | None = Query(default=None, ge=0, le=30),
    posted_within_days: int = Query(default=15, ge=1, le=15),
    location: str | None = Query(default=None, max_length=200),
    remote_only: bool | None = Query(default=None),
    sort: str = Query(default="posted_date", pattern="^(posted_date|company|title|first_seen)$"),
    cursor: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=50, ge=1, le=200),
    new_since: datetime | None = Query(default=None),
    new_in_last_run: bool = Query(default=False),
    include_total: bool = Query(default=False),
    s: Session = Depends(get_session),
) -> JobsListOut:
    filters = _filters_from_query(
        company_ids=company_ids,
        keywords=keywords,
        keyword_logic=keyword_logic,
        experience_min=experience_min,
        experience_max=experience_max,
        posted_within_days=posted_within_days,
        location=location,
        remote_only=remote_only,
        sort=sort,
        new_since=new_since,
        new_in_last_run=new_in_last_run,
    )
    try:
        stmt = build_jobs_query(filters, cursor=cursor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Pull limit+1 to know if there's another page.
    rows = s.execute(stmt.limit(limit + 1)).all()
    page = rows[:limit]
    items = [_to_job_out(job, company_name, keywords) for (job, company_name) in page]

    next_cursor = None
    if len(rows) > limit:
        last_job, last_company = page[-1]
        next_cursor = cursor_for_row(filters, last_job, last_company)

    total: int | None = None
    if include_total:
        # Count over the filtered query (without cursor) — used by the dashboard
        # header when the user explicitly requests it (default off because
        # COUNT(*) defeats keyset pagination's main perf benefit).
        count_filters = _filters_from_query(
            company_ids=company_ids,
            keywords=keywords,
            keyword_logic=keyword_logic,
            experience_min=experience_min,
            experience_max=experience_max,
            posted_within_days=posted_within_days,
            location=location,
            remote_only=remote_only,
            sort=sort,
            new_since=new_since,
            new_in_last_run=new_in_last_run,
        )
        base = build_jobs_query(count_filters, cursor=None).order_by(None)
        total = s.scalar(select(func.count()).select_from(base.subquery())) or 0

    return JobsListOut(items=items, next_cursor=next_cursor, total=total)


@router.get("/export.csv")
def export_jobs_csv(
    company_ids: list[int] | None = Query(default=None),
    keywords: list[str] | None = Query(default=None),
    keyword_logic: str = Query(default="or", pattern="^(and|or)$"),
    experience_min: int | None = Query(default=None, ge=0, le=30),
    experience_max: int | None = Query(default=None, ge=0, le=30),
    posted_within_days: int = Query(default=15, ge=1, le=15),
    location: str | None = Query(default=None, max_length=200),
    remote_only: bool | None = Query(default=None),
    sort: str = Query(default="posted_date", pattern="^(posted_date|company|title|first_seen)$"),
    new_since: datetime | None = Query(default=None),
    new_in_last_run: bool = Query(default=False),
    s: Session = Depends(get_session),
) -> StreamingResponse:
    filters = _filters_from_query(
        company_ids=company_ids,
        keywords=keywords,
        keyword_logic=keyword_logic,
        experience_min=experience_min,
        experience_max=experience_max,
        posted_within_days=posted_within_days,
        location=location,
        remote_only=remote_only,
        sort=sort,
        new_since=new_since,
        new_in_last_run=new_in_last_run,
    )
    stmt = build_jobs_query(filters, cursor=None)

    columns = [
        "company", "title", "location", "remote_type", "department",
        "employment_type", "experience_min", "experience_max",
        "posted_date", "apply_url", "keywords_matched",
    ]

    def _row_iter() -> Iterator[bytes]:
        # Write header
        buf = StringIO()
        w = csv.writer(buf)
        w.writerow(columns)
        yield buf.getvalue().encode("utf-8")

        # Stream rows in chunks via SA `.yield_per()` so memory stays bounded
        # even at 50k rows.
        result = s.execute(stmt.execution_options(yield_per=500))
        for job, company_name in result:
            buf = StringIO()
            w = csv.writer(buf)
            w.writerow(
                [
                    company_name,
                    job.title,
                    job.location or "",
                    job.remote_type or "",
                    job.department or "",
                    job.employment_type or "",
                    job.experience_min if job.experience_min is not None else "",
                    job.experience_max if job.experience_max is not None else "",
                    job.posted_date.isoformat() if job.posted_date else "",
                    job.apply_url,
                    ";".join(matched_keywords(job, keywords)),
                ]
            )
            yield buf.getvalue().encode("utf-8")

    filename = f"jobpulse_export_{datetime.utcnow():%Y%m%d_%H%M}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(_row_iter(), media_type="text/csv", headers=headers)


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, s: Session = Depends(get_session)) -> JobOut:
    row = s.execute(
        select(Job, Company.name).join(Company, Company.id == Job.company_id).where(Job.id == job_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    job, company_name = row
    return _to_job_out(job, company_name, None)
