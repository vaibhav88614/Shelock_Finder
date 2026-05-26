"""Scrape orchestrator (phase 3).

Single-process, manual-trigger model — no scheduler, no workers. The user runs
`python run.py scrape` and this module does the rest:

    1. Open a new `ScrapeRun` row (status="running", started_at=now).
    2. Select active companies (or the subset requested via CLI flags).
    3. Fan out: `asyncio.Semaphore(10)` + per-ATS token-bucket gating.
       Each company is wrapped in its own try/except + 60s timeout so a single
       broken site can never abort the whole run (spec §6).
    4. Per company: `adapter.fetch()` (async, gated) → `adapter.normalize()` →
       persist via `_persist_company()` (run in a worker thread via
       `asyncio.to_thread` so SQLite writes don't block the event loop).
    5. Persistence uses a SELECT-then-INSERT-or-UPDATE pattern keyed by
       fingerprint:
         - new fingerprint  → INSERT with first_seen_at = last_seen_at = started_at.
                              counts as a "new" job and is included in the
                              delta CSV.
         - existing         → UPDATE last_seen_at = started_at, is_active = 1
                              (and refresh mutable fields).
    6. After every company is done: mark `is_active = 0` for jobs of scraped
       companies whose `last_seen_at < started_at` (they disappeared from the
       careers page).
    7. Retention prune: delete jobs where `posted_date < now - 15 days`
       AND `is_active = 0`.
    8. Write the delta CSV: every row where `first_seen_at == started_at`
       AND `company_id IN (scraped_ids)`. Path:
           data/last_run_new_jobs_<YYYYMMDD_HHMMSS>.csv
    9. Close out the `ScrapeRun`: status="ok"/"partial"/"failed", totals,
       finished_at = now. Bump `consecutive_failures` per failing company,
       auto-deactivate after 5.
"""
from __future__ import annotations

import asyncio
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import httpx
from loguru import logger
from sqlalchemy import and_, delete, or_, select, update

from .adapters import ADAPTERS, AdapterError, NormalizedJob, get_adapter_cls
from .adapters.base import BaseAdapter, fingerprint
from .config import settings
from .db import SessionLocal, session_scope
from .migrations import upgrade_to_head
from .models import Company, Job, ScrapeRun, ScrapeRunCompany
from .rate_limit import RateLimiterGroup


# Hard limits from spec §6.
GLOBAL_CONCURRENCY = 10
PER_COMPANY_TIMEOUT_S = 60.0
AUTO_DEACTIVATE_AFTER = 5


# ---------------------------------------------------------------------------
# Public entry point (called from run.py)
# ---------------------------------------------------------------------------


def run_scrape(
    company: str | None = None,
    ats: str | None = None,
    since: str | None = None,
    no_playwright: bool = False,
) -> int:
    """Synchronous wrapper around the async orchestrator.

    Returns the `scrape_runs.id` of the run that was just executed, or 0 if
    no companies matched the filters.
    """
    upgrade_to_head()

    company_ids = _resolve_company_selection(company=company, ats=ats)
    if not company_ids:
        logger.warning(
            "No active companies matched the filters (company={}, ats={}). Nothing to do.",
            company,
            ats,
        )
        return 0

    since_dt = _parse_since(since)
    if no_playwright:
        company_ids = _drop_playwright(company_ids)
        logger.info("--no-playwright set: Tier-3 adapters skipped ({} remaining).", len(company_ids))
        if not company_ids:
            logger.warning("All matched companies require Playwright; nothing to scrape.")
            return 0

    logger.info(
        "Starting scrape: {} companies, retention={} days, since_override={}",
        len(company_ids),
        settings.retention_days,
        since_dt.isoformat() if since_dt else "none",
    )

    return asyncio.run(_orchestrate(company_ids))


def _drop_playwright(company_ids: list[int]) -> list[int]:
    with session_scope() as s:
        rows = s.execute(
            select(Company.id, Company.ats_type).where(Company.id.in_(company_ids))
        ).all()
        return [cid for (cid, ats) in rows if ats != "playwright"]


# ---------------------------------------------------------------------------
# Company selection
# ---------------------------------------------------------------------------


def _resolve_company_selection(company: str | None, ats: str | None) -> list[int]:
    with session_scope() as s:
        stmt = select(Company).where(Company.active.is_(True))
        if ats:
            stmt = stmt.where(Company.ats_type == ats)
        if company:
            try:
                cid = int(company)
                stmt = stmt.where(Company.id == cid)
            except ValueError:
                stmt = stmt.where(Company.name.ilike(company))
        rows = list(s.scalars(stmt))

        adapters_known = set(ADAPTERS.keys())
        out: list[int] = []
        for c in rows:
            if c.ats_type in adapters_known:
                out.append(c.id)
            else:
                logger.debug(
                    "Skipping company id={} ats_type={!r}: no adapter registered yet.",
                    c.id,
                    c.ats_type,
                )
        return out


def _parse_since(since: str | None) -> datetime | None:
    if not since:
        return None
    try:
        return datetime.fromisoformat(since)
    except ValueError as e:
        raise SystemExit(f"--since must be ISO date (YYYY-MM-DD): {e}") from e


# ---------------------------------------------------------------------------
# Async orchestration
# ---------------------------------------------------------------------------


async def _orchestrate(company_ids: list[int]) -> int:
    started_at = datetime.utcnow()

    with session_scope() as s:
        run = ScrapeRun(started_at=started_at, status="running")
        s.add(run)
        s.flush()
        run_id = run.id
    logger.info("Opened scrape_run id={} at {}", run_id, started_at.isoformat())

    semaphore = asyncio.Semaphore(GLOBAL_CONCURRENCY)
    buckets = RateLimiterGroup()

    async with httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        # Cache one adapter per ATS family, sharing the pooled client.
        adapter_cache: dict[str, BaseAdapter] = {}
        for ats_type in set(_company_ats_types(company_ids)):
            cls = get_adapter_cls(ats_type)
            adapter_cache[ats_type] = cls(client=client)

        tasks = [
            asyncio.create_task(
                _scrape_one(cid, run_id, started_at, adapter_cache, semaphore, buckets)
            )
            for cid in company_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)

    total_found = sum(r.jobs_found for r in results)
    total_new = sum(r.jobs_new for r in results)
    n_ok = sum(1 for r in results if r.status == "ok")
    n_fail = len(results) - n_ok

    await asyncio.to_thread(
        _finalize_run, run_id, started_at, company_ids, total_found, total_new, n_ok, n_fail
    )
    delta_path = await asyncio.to_thread(
        _write_delta_csv, run_id, started_at, company_ids
    )

    logger.info(
        "Scrape complete: run_id={} companies={} ok={} failed={} jobs_found={} jobs_new={} delta_csv={}",
        run_id,
        len(company_ids),
        n_ok,
        n_fail,
        total_found,
        total_new,
        delta_path.name,
    )
    return run_id


def _company_ats_types(company_ids: list[int]) -> Iterable[str]:
    with session_scope() as s:
        return [
            t for (t,) in s.execute(
                select(Company.ats_type).where(Company.id.in_(company_ids))
            ).all()
        ]


# ---------------------------------------------------------------------------
# Per-company task
# ---------------------------------------------------------------------------


@dataclass
class _PerCompanyResult:
    company_id: int
    status: str  # "ok" | "failed"
    jobs_found: int
    jobs_new: int
    error: str | None


async def _scrape_one(
    company_id: int,
    run_id: int,
    started_at: datetime,
    adapter_cache: dict[str, BaseAdapter],
    semaphore: asyncio.Semaphore,
    buckets: RateLimiterGroup,
) -> _PerCompanyResult:
    company_snapshot = await asyncio.to_thread(_load_company_snapshot, company_id)
    if company_snapshot is None:
        return _PerCompanyResult(company_id, "failed", 0, 0, "company missing")

    adapter = adapter_cache.get(company_snapshot.ats_type)
    if adapter is None:
        return await asyncio.to_thread(
            _record_company_failure, run_id, company_id, "no adapter registered"
        )

    async with semaphore:
        try:
            await buckets.acquire(company_snapshot.ats_type)
            raws = await asyncio.wait_for(adapter.fetch(company_snapshot), PER_COMPANY_TIMEOUT_S)
        except asyncio.TimeoutError:
            return await asyncio.to_thread(
                _record_company_failure,
                run_id,
                company_id,
                f"timeout after {PER_COMPANY_TIMEOUT_S}s",
            )
        except AdapterError as e:
            return await asyncio.to_thread(_record_company_failure, run_id, company_id, str(e))
        except Exception as e:  # noqa: BLE001 — isolate per spec §10
            logger.exception("Unexpected error scraping company id={}", company_id)
            return await asyncio.to_thread(
                _record_company_failure, run_id, company_id, f"unexpected: {e!r}"
            )

    normalized: list[NormalizedJob] = []
    for raw in raws:
        try:
            normalized.append(adapter.normalize(raw, company_snapshot))
        except Exception as e:  # noqa: BLE001
            logger.warning("company id={} normalize() failed for one entry: {}", company_id, e)

    return await asyncio.to_thread(
        _persist_company, run_id, company_id, started_at, normalized
    )


# ---------------------------------------------------------------------------
# DB I/O (sync, runs in worker threads)
# ---------------------------------------------------------------------------


@dataclass
class _CompanySnapshot:
    """Detached view of a Company for use across the async/thread boundary."""

    id: int
    name: str
    ats_type: str
    ats_identifier: str | None
    careers_url: str
    custom_selectors: dict | None


def _load_company_snapshot(company_id: int) -> _CompanySnapshot | None:
    with session_scope() as s:
        c = s.get(Company, company_id)
        if c is None:
            return None
        sel = None
        if c.custom_selectors:
            try:
                sel = json.loads(c.custom_selectors)
            except json.JSONDecodeError:
                sel = None
        return _CompanySnapshot(
            id=c.id,
            name=c.name,
            ats_type=c.ats_type,
            ats_identifier=c.ats_identifier,
            careers_url=c.careers_url,
            custom_selectors=sel,
        )


def _record_company_failure(run_id: int, company_id: int, error: str) -> _PerCompanyResult:
    with session_scope() as s:
        s.add(
            ScrapeRunCompany(
                scrape_run_id=run_id,
                company_id=company_id,
                status="failed",
                jobs_found=0,
                jobs_new=0,
                error_message=error[:2000],
            )
        )
        c = s.get(Company, company_id)
        if c is not None:
            c.last_scraped_at = datetime.utcnow()
            c.consecutive_failures = (c.consecutive_failures or 0) + 1
            if c.consecutive_failures >= AUTO_DEACTIVATE_AFTER:
                c.active = False
                logger.warning(
                    "Auto-deactivating company {!r} after {} consecutive failures.",
                    c.name,
                    c.consecutive_failures,
                )
    logger.warning("company id={} failed: {}", company_id, error)
    return _PerCompanyResult(company_id, "failed", 0, 0, error)


def _persist_company(
    run_id: int,
    company_id: int,
    started_at: datetime,
    normalized: list[NormalizedJob],
) -> _PerCompanyResult:
    """Upsert normalized jobs and write one ScrapeRunCompany row."""
    jobs_found = len(normalized)
    jobs_new = 0

    # Dedupe within the batch (some careers pages list the same role twice
    # under different categories).
    by_fp: dict[str, NormalizedJob] = {}
    for nj in normalized:
        if not nj.title or not nj.apply_url:
            continue
        fp = fingerprint(company_id, nj.external_id, nj.title, nj.location, nj.apply_url)
        by_fp[fp] = nj
    fps = list(by_fp.keys())

    with session_scope() as s:
        existing: dict[str, Job] = {}
        for chunk in _chunks(fps, 500):
            rows = s.scalars(
                select(Job).where(
                    and_(Job.company_id == company_id, Job.fingerprint.in_(chunk))
                )
            ).all()
            for j in rows:
                existing[j.fingerprint] = j

        for fp, nj in by_fp.items():
            row = existing.get(fp)
            if row is None:
                s.add(
                    Job(
                        company_id=company_id,
                        external_id=nj.external_id,
                        fingerprint=fp,
                        title=nj.title,
                        description=nj.description,
                        location=nj.location,
                        remote_type=nj.remote_type,
                        department=nj.department,
                        employment_type=nj.employment_type,
                        experience_min=nj.experience_min,
                        experience_max=nj.experience_max,
                        posted_date=nj.posted_date,
                        apply_url=nj.apply_url,
                        raw_payload=(
                            json.dumps(nj.raw_payload, default=str)[:200_000]
                            if nj.raw_payload
                            else None
                        ),
                        first_seen_at=started_at,
                        last_seen_at=started_at,
                        is_active=True,
                    )
                )
                jobs_new += 1
            else:
                # Refresh mutable fields; never bump first_seen_at.
                row.title = nj.title
                row.description = nj.description
                row.location = nj.location
                row.remote_type = nj.remote_type
                row.department = nj.department
                row.employment_type = nj.employment_type
                if nj.experience_min is not None:
                    row.experience_min = nj.experience_min
                if nj.experience_max is not None:
                    row.experience_max = nj.experience_max
                if nj.posted_date is not None:
                    row.posted_date = nj.posted_date
                row.apply_url = nj.apply_url
                row.last_seen_at = started_at
                row.is_active = True

        s.add(
            ScrapeRunCompany(
                scrape_run_id=run_id,
                company_id=company_id,
                status="ok",
                jobs_found=jobs_found,
                jobs_new=jobs_new,
            )
        )

        c = s.get(Company, company_id)
        if c is not None:
            now = datetime.utcnow()
            c.last_scraped_at = now
            c.last_success_at = now
            c.consecutive_failures = 0

    logger.info("company id={} ok: found={} new={}", company_id, jobs_found, jobs_new)
    return _PerCompanyResult(company_id, "ok", jobs_found, jobs_new, None)


def _finalize_run(
    run_id: int,
    started_at: datetime,
    company_ids: list[int],
    total_found: int,
    total_new: int,
    n_ok: int,
    n_fail: int,
) -> None:
    with session_scope() as s:
        # Mark jobs we *didn't* see this run as inactive (spec §4.3).
        s.execute(
            update(Job)
            .where(
                and_(
                    Job.company_id.in_(company_ids),
                    Job.last_seen_at < started_at,
                    Job.is_active.is_(True),
                )
            )
            .values(is_active=False)
        )

        # Retention prune (spec §4.5).
        cutoff = datetime.utcnow() - timedelta(days=settings.retention_days)
        s.execute(
            delete(Job).where(
                and_(
                    Job.is_active.is_(False),
                    or_(Job.posted_date.is_(None), Job.posted_date < cutoff),
                )
            )
        )

        run = s.get(ScrapeRun, run_id)
        if run is not None:
            run.finished_at = datetime.utcnow()
            run.companies_scraped = len(company_ids)
            run.jobs_found_total = total_found
            run.jobs_new_total = total_new
            if n_fail == 0:
                run.status = "ok"
            elif n_ok == 0:
                run.status = "failed"
            else:
                run.status = "partial"
            if n_fail:
                run.error_summary = f"{n_fail} of {len(company_ids)} companies failed"


CSV_COLUMNS = [
    "company",
    "title",
    "location",
    "remote_type",
    "department",
    "employment_type",
    "experience_min",
    "experience_max",
    "posted_date",
    "apply_url",
    "first_seen_at",
]


def _write_delta_csv(
    run_id: int, started_at: datetime, company_ids: list[int]
) -> Path:
    """Write `data/last_run_new_jobs_<ts>.csv` with rows newly seen this run."""
    out_path = settings.data_dir / f"last_run_new_jobs_{started_at:%Y%m%d_%H%M%S}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with SessionLocal() as s, out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        stmt = (
            select(Job, Company.name)
            .join(Company, Company.id == Job.company_id)
            .where(
                and_(
                    Job.company_id.in_(company_ids),
                    Job.first_seen_at == started_at,
                )
            )
            .order_by(Company.name, Job.title)
        )
        for job, company_name in s.execute(stmt).all():
            writer.writerow(
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
                    job.first_seen_at.isoformat(),
                ]
            )
            written += 1
    logger.info("Delta CSV written: {} ({} rows)", out_path.name, written)
    return out_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chunks(lst, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]
