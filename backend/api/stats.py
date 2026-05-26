"""/api/v1/stats — dashboard header + admin/health summary."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Company, Job, ScrapeRun
from .schemas import CompanyHealth, ScrapeRunOut, StatsOut


router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("", response_model=StatsOut)
def get_stats(s: Session = Depends(get_session)) -> StatsOut:
    cutoff_15d = datetime.utcnow() - timedelta(days=15)

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
                last_scraped_at=c.last_scraped_at,
                last_success_at=c.last_success_at,
                consecutive_failures=c.consecutive_failures,
                jobs_active=int(counts.get(c.id, 0)),
            )
        )
    return out
