"""/api/v1/scrape-runs — observability for past runs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import ScrapeRun
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
