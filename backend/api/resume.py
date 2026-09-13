"""/api/v1/resume — upload, inspect, and rescore the active resume.

Endpoints
---------
GET    /resume            → current resume metadata (or ``None``)
POST   /resume            → upload plain-text resume (JSON body)
POST   /resume/upload     → upload as multipart file (PDF / txt / md)
DELETE /resume            → clear the active resume + cached matches
POST   /resume/rescore    → force full rescore against every active job

All mutating endpoints go through ``require_api_key`` — the resume is user
data, and even in local mode we treat it as such.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Resume
from ..resume import (
    extract_text_from_upload,
    load_active_resume,
    rescore_resume,
    save_resume,
    match_count,
)
from .deps import require_api_key


router = APIRouter(prefix="/resume", tags=["resume"])


class ResumeOut(BaseModel):
    id: int
    name: str
    filename: str | None
    uploaded_at: datetime
    scored_at: datetime | None
    text_length: int
    bag_size: int
    matches_total: int
    matches_nonzero: int


class ResumeTextIn(BaseModel):
    text: str = Field(..., min_length=20, max_length=200_000)
    name: str = Field(default="primary", min_length=1, max_length=255)


class RescoreResult(BaseModel):
    resume_id: int
    scored: int
    nonzero: int
    top_score: float
    duration_s: float


def _to_out(r: Resume) -> ResumeOut:
    import json as _json

    try:
        bag = _json.loads(r.tokens or "{}")
        bag_size = len(bag) if isinstance(bag, dict) else 0
    except _json.JSONDecodeError:
        bag_size = 0
    return ResumeOut(
        id=r.id,
        name=r.name,
        filename=r.filename,
        uploaded_at=r.uploaded_at,
        scored_at=r.scored_at,
        text_length=len(r.text or ""),
        bag_size=bag_size,
        matches_total=match_count(r.id),
        matches_nonzero=match_count(r.id, threshold=0.0001),
    )


@router.get("", response_model=ResumeOut | None)
def get_resume(s: Session = Depends(get_session)) -> ResumeOut | None:
    r = load_active_resume(s)
    return _to_out(r) if r else None


def _rescore_bg(resume_id: int) -> None:
    """Trampoline so a bg task's exception never disappears into a silent
    void — loguru catches it, and the row's ``scored_at`` stays None to
    signal the failure to the UI."""
    from loguru import logger

    try:
        rescore_resume(resume_id)
    except Exception:  # noqa: BLE001
        logger.exception("background rescore failed for resume_id={}", resume_id)


@router.post("", response_model=ResumeOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_api_key)])
def create_resume(
    payload: ResumeTextIn,
    background: BackgroundTasks,
    s: Session = Depends(get_session),
) -> ResumeOut:
    row = save_resume(s, text=payload.text, name=payload.name, filename=None)
    s.commit()
    background.add_task(_rescore_bg, row.id)
    return _to_out(row)


@router.post("/upload", response_model=ResumeOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_api_key)])
async def upload_resume(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    s: Session = Depends(get_session),
) -> ResumeOut:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty upload")
    try:
        text = extract_text_from_upload(
            raw, content_type=file.content_type, filename=file.filename
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="no text extracted — try uploading a plain-text version",
        )
    row = save_resume(
        s, text=text, name=file.filename or "resume", filename=file.filename
    )
    s.commit()
    background.add_task(_rescore_bg, row.id)
    return _to_out(row)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, response_model=None,
               dependencies=[Depends(require_api_key)])
def delete_resume(s: Session = Depends(get_session)) -> None:
    r = load_active_resume(s)
    if r is None:
        raise HTTPException(status_code=404, detail="no active resume")
    s.delete(r)
    s.commit()


@router.post("/rescore", response_model=RescoreResult,
             dependencies=[Depends(require_api_key)])
def rescore(
    background: BackgroundTasks,
    s: Session = Depends(get_session),
) -> RescoreResult:
    r = load_active_resume(s)
    if r is None:
        raise HTTPException(status_code=404, detail="no active resume")
    # Delegate to the same worker path — matches the /upload semantics and
    # keeps HTTP timings snappy even on 30k-row corpora.
    background.add_task(_rescore_bg, r.id)
    return RescoreResult(
        resume_id=r.id, scored=0, nonzero=0, top_score=0.0, duration_s=0.0,
    )
