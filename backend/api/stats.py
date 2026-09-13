"""/api/v1/stats — dashboard header + admin/health summary + facets + sparklines."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Company, Job, ScrapeRun, utcnow_naive
from .schemas import (
    CompanyHealth,
    LocationFacet,
    LocationFacetsOut,
    ScrapeRunOut,
    SparklinePoint,
    SparklinesOut,
    StatsOut,
)


router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("", response_model=StatsOut)
def get_stats(s: Session = Depends(get_session)) -> StatsOut:
    cutoff_15d = utcnow_naive() - timedelta(days=15)

    jobs_total = s.scalar(select(func.count()).select_from(Job)) or 0
    jobs_active = s.scalar(
        select(func.count()).select_from(Job).where(Job.is_active.is_(True))
    ) or 0
    jobs_last_15d = s.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.is_active.is_(True))
        .where((Job.posted_date.is_(None)) | (Job.posted_date >= cutoff_15d))
    ) or 0

    companies_total = s.scalar(select(func.count()).select_from(Company)) or 0
    companies_active = s.scalar(
        select(func.count()).select_from(Company).where(Company.active.is_(True))
    ) or 0

    last_run_row = s.scalar(select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(1))
    last_run = ScrapeRunOut.model_validate(last_run_row) if last_run_row else None

    return StatsOut(
        jobs_total=jobs_total,
        jobs_active=jobs_active,
        jobs_last_15d=jobs_last_15d,
        companies_total=companies_total,
        companies_active=companies_active,
        last_run=last_run,
    )


@router.get("/companies", response_model=list[CompanyHealth])
def companies_health(s: Session = Depends(get_session)) -> list[CompanyHealth]:
    """Per-company scrape health, used by the admin page."""
    # jobs_active per company
    counts = dict(
        s.execute(
            select(Job.company_id, func.count())
            .where(Job.is_active.is_(True))
            .group_by(Job.company_id)
        ).all()
    )
    out: list[CompanyHealth] = []
    for c in s.scalars(select(Company).order_by(Company.name)):
        out.append(
            CompanyHealth(
                id=c.id,
                name=c.name,
                ats_type=c.ats_type,
                active=c.active,
                has_selectors=c.ats_type in ("custom", "playwright")
                and bool(c.custom_selectors),
                last_scraped_at=c.last_scraped_at,
                last_success_at=c.last_success_at,
                consecutive_failures=c.consecutive_failures,
                jobs_active=int(counts.get(c.id, 0)),
            )
        )
    return out


@router.get("/facets/locations", response_model=LocationFacetsOut)
def location_facets(
    limit: int = Query(default=15, ge=1, le=100),
    posted_within_days: int = Query(default=15, ge=1, le=365),
    s: Session = Depends(get_session),
) -> LocationFacetsOut:
    """Return the top-N cities / countries / regions among ACTIVE jobs.

    The dashboard turns each row into a clickable filter chip. Bucketed by
    ``posted_within_days`` (default 15 = the front-end's default window) so
    stale rows don't pad the counts.
    """
    cutoff = utcnow_naive() - timedelta(days=posted_within_days)
    active_and_recent = (
        Job.is_active.is_(True),
        (Job.posted_date.is_(None)) | (Job.posted_date >= cutoff),
    )

    def _facet(col) -> list[LocationFacet]:  # noqa: ANN001 — col is an SA ColumnElement
        rows = s.execute(
            select(col, func.count())
            .where(*active_and_recent)
            .where(col.is_not(None))
            .where(col != "")
            .group_by(col)
            .order_by(func.count().desc(), col.asc())
            .limit(limit)
        ).all()
        return [LocationFacet(value=v, count=int(n)) for v, n in rows]

    cities = _facet(Job.city)
    countries = _facet(Job.country)
    regions = _facet(Job.region)

    remote_count = int(
        s.scalar(
            select(func.count())
            .select_from(Job)
            .where(*active_and_recent)
            .where(Job.is_remote.is_(True))
        )
        or 0
    )
    onsite_count = int(
        s.scalar(
            select(func.count())
            .select_from(Job)
            .where(*active_and_recent)
            .where(Job.is_remote.is_(False))
        )
        or 0
    )
    return LocationFacetsOut(
        cities=cities,
        countries=countries,
        regions=regions,
        remote=remote_count,
        onsite=onsite_count,
    )


@router.get("/sparklines", response_model=SparklinesOut)
def sparklines(
    days: int = Query(default=30, ge=7, le=90),
    run_window: int = Query(default=25, ge=5, le=100),
    s: Session = Depends(get_session),
) -> SparklinesOut:
    """Compact daily + per-run series used to fill the dashboard tile sparklines.

    * ``new_jobs_per_day`` — count grouped by DATE(first_seen_at) inside the
      window. Days with zero postings are filled explicitly so the sparkline
      X-axis stays gap-free.
    * ``active_per_day``   — currently-active jobs whose posted_date falls on
      each day (proxy for "active on that day", cheap and index-friendly).
    * ``runs_jobs_new`` / ``runs_jobs_found`` — arrays over the last
      ``run_window`` finished scrape runs, oldest first, so the client can
      render them left-to-right.
    """
    now = utcnow_naive()
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    # ---- daily new-job series ------------------------------------------------
    # SQLite's DATE() over a datetime column yields "YYYY-MM-DD" text, which
    # is exactly what we need for the X-axis label.
    new_day_col = func.date(Job.first_seen_at).label("d")
    rows = s.execute(
        select(new_day_col, func.count())
        .where(Job.first_seen_at >= start)
        .group_by(new_day_col)
        .order_by(new_day_col.asc())
    ).all()
    new_by_day = {r[0]: int(r[1]) for r in rows}

    active_day_col = func.date(Job.posted_date).label("d")
    active_rows = s.execute(
        select(active_day_col, func.count())
        .where(Job.is_active.is_(True))
        .where(Job.posted_date >= start)
        .group_by(active_day_col)
        .order_by(active_day_col.asc())
    ).all()
    active_by_day = {r[0]: int(r[1]) for r in active_rows}

    # Densify the arrays so the client can render gap-free — one point per
    # day in the window (0 when nothing was posted).
    daily_new: list[SparklinePoint] = []
    daily_active: list[SparklinePoint] = []
    for i in range(days):
        d: date = (start + timedelta(days=i)).date()
        key = d.isoformat()
        daily_new.append(SparklinePoint(label=key, value=new_by_day.get(key, 0)))
        daily_active.append(SparklinePoint(label=key, value=active_by_day.get(key, 0)))

    # ---- per-run series ------------------------------------------------------
    run_rows = list(
        s.execute(
            select(ScrapeRun)
            .where(ScrapeRun.finished_at.is_not(None))
            .order_by(ScrapeRun.started_at.desc())
            .limit(run_window)
        ).scalars()
    )
    # Reverse so oldest → newest matches sparkline left-to-right convention.
    run_rows.reverse()

    return SparklinesOut(
        new_jobs_per_day=daily_new,
        active_per_day=daily_active,
        runs_jobs_new=[
            SparklinePoint(label=f"#{r.id}", value=int(r.jobs_new_total or 0))
            for r in run_rows
        ],
        runs_jobs_found=[
            SparklinePoint(label=f"#{r.id}", value=int(r.jobs_found_total or 0))
            for r in run_rows
        ],
    )
