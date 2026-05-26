"""/api/v1/companies CRUD + bulk import + manual scrape trigger."""
from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..detect import detect_ats
from ..models import Company
from .deps import require_api_key
from .schemas import (
    CompanyBulkImportResult,
    CompanyCreate,
    CompanyOut,
    CompanyUpdate,
    DetectAtsOut,
)


router = APIRouter(prefix="/companies", tags=["companies"])


def _to_out(c: Company) -> CompanyOut:
    return CompanyOut.model_validate(c)


@router.get("", response_model=list[CompanyOut])
def list_companies(
    active: bool | None = None,
    ats_type: str | None = None,
    s: Session = Depends(get_session),
) -> list[CompanyOut]:
    stmt = select(Company).order_by(Company.name)
    if active is not None:
        stmt = stmt.where(Company.active.is_(active))
    if ats_type:
        stmt = stmt.where(Company.ats_type == ats_type)
    return [_to_out(c) for c in s.scalars(stmt)]


@router.get("/detect", response_model=DetectAtsOut)
def detect_company_ats(url: str = Query(..., min_length=8, max_length=2048)) -> DetectAtsOut:
    """Classify a careers URL into an ATS family without writing anything.

    Used by the Add-Company UI to show a live preview before submitting. Pure
    function — no HTTP fetched, no DB row created.
    """
    ats_type, ats_id = detect_ats(url)
    return DetectAtsOut(ats_type=ats_type, ats_identifier=ats_id, recognized=ats_type is not None)


@router.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_api_key)])
def create_company(payload: CompanyCreate, s: Session = Depends(get_session)) -> CompanyOut:
    if s.scalar(select(Company).where(Company.name == payload.name)):
        raise HTTPException(status_code=409, detail="company name already exists")

    # Auto-detect ATS from URL unless the caller explicitly provided one.
    final_type = payload.ats_type
    final_id = payload.ats_identifier
    if not final_type:
        detected_type, detected_id = detect_ats(str(payload.careers_url))
        final_type = detected_type or "custom"
        if not final_id:
            final_id = detected_id

    c = Company(
        name=payload.name,
        careers_url=str(payload.careers_url),
        ats_type=final_type,
        ats_identifier=final_id,
        custom_selectors=json.dumps(payload.custom_selectors) if payload.custom_selectors else None,
        active=payload.active,
    )
    s.add(c)
    s.commit()
    s.refresh(c)
    return _to_out(c)


@router.patch("/{company_id}", response_model=CompanyOut,
              dependencies=[Depends(require_api_key)])
def update_company(
    company_id: int,
    payload: CompanyUpdate,
    s: Session = Depends(get_session),
) -> CompanyOut:
    c = s.get(Company, company_id)
    if c is None:
        raise HTTPException(status_code=404, detail="company not found")
    data = payload.model_dump(exclude_unset=True)
    if "careers_url" in data and data["careers_url"] is not None:
        data["careers_url"] = str(data["careers_url"])
    if "custom_selectors" in data:
        data["custom_selectors"] = (
            json.dumps(data["custom_selectors"]) if data["custom_selectors"] else None
        )
    for k, v in data.items():
        setattr(c, k, v)
    s.commit()
    s.refresh(c)
    return _to_out(c)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT,
               response_model=None,
               dependencies=[Depends(require_api_key)])
def delete_company(company_id: int, s: Session = Depends(get_session)) -> None:
    c = s.get(Company, company_id)
    if c is None:
        raise HTTPException(status_code=404, detail="company not found")
    s.delete(c)
    s.commit()


@router.post("/{company_id}/scrape", dependencies=[Depends(require_api_key)])
def trigger_scrape(
    company_id: int,
    background: BackgroundTasks,
    s: Session = Depends(get_session),
) -> dict:
    """Kick off a scrape for one company. Runs in a background thread so the
    HTTP call returns immediately; the run_id of the in-flight ScrapeRun row is
    discoverable via `GET /scrape-runs?limit=1`.
    """
    c = s.get(Company, company_id)
    if c is None:
        raise HTTPException(status_code=404, detail="company not found")

    # Avoid importing at module load (scrape pulls in httpx + asyncio).
    from ..scrape import run_scrape

    def _job() -> None:
        try:
            run_scrape(company=str(company_id))
        except Exception:  # noqa: BLE001
            # Logged via loguru inside run_scrape; never re-raise into the
            # background task's silent void.
            pass

    background.add_task(_job)
    return {"status": "queued", "company_id": company_id}


@router.post("/bulk-import", response_model=CompanyBulkImportResult,
             dependencies=[Depends(require_api_key)])
async def bulk_import(
    file: UploadFile = File(...),
    s: Session = Depends(get_session),
) -> CompanyBulkImportResult:
    """Accept a CSV with at minimum `name` + `careers_url` columns; optional
    `ats_type` and `ats_identifier`. Idempotent on `name`.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty upload")
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "name" not in reader.fieldnames or "careers_url" not in reader.fieldnames:
        raise HTTPException(
            status_code=400,
            detail="CSV must have columns: name, careers_url (optional: ats_type, ats_identifier)",
        )

    inserted = updated = skipped = 0
    errors: list[str] = []

    for line_no, row in enumerate(reader, start=2):  # header is line 1
        name = (row.get("name") or "").strip()
        url = (row.get("careers_url") or "").strip()
        if not name or not url:
            skipped += 1
            errors.append(f"line {line_no}: missing name or careers_url")
            continue
        ats_type = (row.get("ats_type") or "").strip()
        ats_id = (row.get("ats_identifier") or "").strip() or None
        if not ats_type:
            detected_type, detected_id = detect_ats(url)
            ats_type = detected_type or "custom"
            if not ats_id:
                ats_id = detected_id
        try:
            existing = s.scalar(select(Company).where(Company.name == name))
            if existing is None:
                s.add(Company(name=name, careers_url=url, ats_type=ats_type, ats_identifier=ats_id))
                inserted += 1
            else:
                existing.careers_url = url
                existing.ats_type = ats_type
                if ats_id:
                    existing.ats_identifier = ats_id
                updated += 1
        except Exception as e:  # noqa: BLE001
            skipped += 1
            errors.append(f"line {line_no} ({name}): {e}")
    s.commit()

    return CompanyBulkImportResult(
        inserted=inserted, updated=updated, skipped=skipped, errors=errors[:50]
    )
