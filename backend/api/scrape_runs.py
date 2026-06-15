"""/api/v1/scrape-runs — observability for past runs."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import ScrapeRun
from .deps import require_api_key
from .schemas import ScrapeRunOut


router = APIRouter(prefix="/scrape-runs", tags=["scrape-runs"])


@router.get("", response_model=list[ScrapeRunOut])
def list_runs(
    limit: int = Query(default=25, ge=1, le=200),
    s: Session = Depends(get_session),
) -> list[ScrapeRunOut]:
    rows = s.scalars(select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(limit)).all()
    return [ScrapeRunOut.model_validate(r) for r in rows]


@router.get("/{run_id}", response_model=ScrapeRunOut)
def get_run(run_id: int, s: Session = Depends(get_session)) -> ScrapeRunOut:
    r = s.get(ScrapeRun, run_id)
    if r is None:
        raise HTTPException(status_code=404, detail="run not found")
    return ScrapeRunOut.model_validate(r)


@router.post("", status_code=202, dependencies=[Depends(require_api_key)])
def trigger_scrape_all(
    background: BackgroundTasks,
    ats: str | None = Query(default=None, description="Restrict to one ATS family"),
    no_playwright: bool = Query(default=False, description="Skip Playwright-tier sites"),
    s: Session = Depends(get_session),
) -> dict:
    """Queue a full scrape across all active companies.

    Refuses (409) if another run is already in-flight (`finished_at IS NULL`).
    Runs in a FastAPI background task, no Celery/Redis.
    """
    in_flight = s.scalar(
        select(ScrapeRun).where(ScrapeRun.finished_at.is_(None)).limit(1)
    )
    if in_flight is not None:
        raise HTTPException(
            status_code=409,
            detail=f"scrape already in-flight (run_id={in_flight.id})",
        )

    from ..scrape import run_scrape

    def _job() -> None:
        try:
            run_scrape(ats=ats, no_playwright=no_playwright)
        except Exception:  # noqa: BLE001
            pass

    background.add_task(_job)
    return {"status": "queued", "ats": ats, "no_playwright": no_playwright}
