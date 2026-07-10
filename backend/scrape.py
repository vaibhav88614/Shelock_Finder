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
import functools
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import httpx
from loguru import logger
from sqlalchemy import and_, delete, select, update

from .adapters import ADAPTERS, AdapterError, NormalizedJob, get_adapter_cls
from .adapters.base import BaseAdapter, fingerprint
from .config import settings
from .db import SessionLocal, engine, session_scope
from .migrations import upgrade_to_head
from .models import Company, Job, ScrapeRun, ScrapeRunCompany, utcnow_naive
from .rate_limit import RateLimiterGroup


# Hard limits from spec §6.
GLOBAL_CONCURRENCY = 10
PER_COMPANY_TIMEOUT_S = 60.0
AUTO_DEACTIVATE_AFTER = 5


# Country/region tokens that, when already present in a scraped location
# string, mean we must NOT append the company's country (the location is
# already geo-qualified). Lowercased substrings; deliberately conservative so
# we over-preserve rather than double-append.
_COUNTRY_TOKENS = (
    "india", "usa", "united states", "united kingdom",
    "canada", "germany", "france", "spain", "netherlands", "australia",
    "singapore", "brazil", "ireland", "mexico", "poland", "portugal",
    "japan", "china", "worldwide", "global", "emea", "apac", "anywhere",
)

# Standalone short country codes matched on word boundaries (so "us" doesn't
# fire inside "business"/"houston"). Kept separate from the substring tokens
# above because these are too short for a naive `in` check.
_COUNTRY_CODE_RE = re.compile(r"\b(u\.?s\.?a?|u\.?k\.?|u\.?a\.?e\.?|eu)\b", re.IGNORECASE)


def _enrich_location(loc: str | None, company_country: str | None) -> str | None:
    """Ensure a job's location names the company's country when one is known.

    Companies tagged with a `country` (e.g. India) should always have that
    country present in their jobs' `location` so the free-text Location filter
    matches reliably:
      * empty/unknown location -> the country itself ("India");
      * a location lacking any country/region -> "<loc>, India";
      * a location already naming a country/region -> left unchanged.
    No-op when the company has no country.
    """
    if not company_country:
        return loc
    if not loc or not loc.strip():
        return company_country
    lc = loc.lower()
    if company_country.lower() in lc or any(tok in lc for tok in _COUNTRY_TOKENS):
        return loc
    if _COUNTRY_CODE_RE.search(loc):
        return loc
    return f"{loc}, {company_country}"


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
    started_at = utcnow_naive()

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
        # Cache one adapter per ATS family, sharing the pooled client. Each
        # adapter is bound to a rate-token re-acquire callable so retries
        # (inside request_with_retry) re-gate through the same per-ATS bucket
        # instead of hammering an already-throttling server.
        adapter_cache: dict[str, BaseAdapter] = {}
        for ats_type in set(_company_ats_types(company_ids)):
            cls = get_adapter_cls(ats_type)
            adapter = cls(client=client)
            adapter._rate_acquire = functools.partial(buckets.acquire, ats_type)
            adapter_cache[ats_type] = adapter

        try:
            tasks = [
                asyncio.create_task(
                    _scrape_one(cid, run_id, started_at, adapter_cache, semaphore, buckets)
                )
                for cid in company_ids
            ]
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            # Best-effort cleanup of adapter-owned httpx clients. Adapters
            # created with a shared client (current default) treat aclose()
            # as a no-op; this covers the lazy-init path used outside the
            # orchestrator (and any future adapter that opens its own client).
            await asyncio.gather(
                *(a.aclose() for a in adapter_cache.values()),
                return_exceptions=True,
            )

    # Backstop: convert any exception that escaped `_scrape_one`'s own
    # try/except wrappers into a recorded failure so totals stay consistent
    # and one broken company can never abort the whole run (spec §6).
    results: list[_PerCompanyResult] = []
    for cid, r in zip(company_ids, raw_results):
        if isinstance(r, BaseException):
            logger.exception(
                "unhandled exception escaped _scrape_one for company id={}: {!r}",
                cid,
                r,
            )
            results.append(
                await asyncio.to_thread(
                    _record_company_failure, run_id, cid, f"unhandled: {r!r}"
                )
            )
        else:
            results.append(r)

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
    try:
        company_snapshot = await asyncio.to_thread(_load_company_snapshot, company_id)
    except Exception as e:  # noqa: BLE001 — isolate per spec §6
        logger.exception("company id={} snapshot load failed", company_id)
        return await asyncio.to_thread(
            _record_company_failure, run_id, company_id, f"snapshot load failed: {e!r}"
        )
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

    try:
        return await asyncio.to_thread(
            _persist_company,
            run_id,
            company_id,
            started_at,
            normalized,
            company_snapshot.country,
        )
    except Exception as e:  # noqa: BLE001 — isolate per spec §6
        logger.exception("company id={} persist failed", company_id)
        return await asyncio.to_thread(
            _record_company_failure, run_id, company_id, f"persist failed: {e!r}"
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
    country: str | None = None


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
            country=c.country,
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
            c.last_scraped_at = utcnow_naive()
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
    company_country: str | None = None,
) -> _PerCompanyResult:
    """Upsert normalized jobs and write one ScrapeRunCompany row."""
    jobs_found = len(normalized)
    jobs_new = 0

    # Dedupe within the batch (some careers pages list the same role twice
    # under different categories).
    by_fp: dict[str, NormalizedJob] = {}
    for nj in normalized:
        if not nj.title or not nj.apply_url:
            logger.warning(
                "dropped job missing title/apply_url: company_id={}, external_id={!r}, title={!r}",
                company_id,
                nj.external_id,
                nj.title,
            )
            continue
        # Normalize location so a country-tagged company's jobs always carry
        # that country, letting the free-text Location filter match. Done
        # before fingerprinting so the fingerprint stays stable across runs.
        nj.location = _enrich_location(nj.location, company_country)
        fp = fingerprint(company_id, nj.external_id, nj.title, nj.location, nj.apply_url)
        by_fp[fp] = nj
    items = list(by_fp.items())

    with session_scope() as s:
        # Process in 500-job chunks so memory and writer lock-hold stay
        # bounded for large boards (Workday tenants, Stripe — 1000+ postings).
        # The existing-row SELECT is bounded by the chunk size; new rows are
        # added incrementally and flushed each chunk to push pending state
        # out of the unit-of-work map.
        for chunk_start in range(0, len(items), 500):
            chunk = items[chunk_start : chunk_start + 500]
            chunk_fps = [fp for fp, _ in chunk]
            existing_rows = s.scalars(
                select(Job).where(
                    and_(Job.company_id == company_id, Job.fingerprint.in_(chunk_fps))
                )
            ).all()
            existing = {j.fingerprint: j for j in existing_rows}

            for fp, nj in chunk:
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
                                if nj.raw_payload and settings.store_raw_payload
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
            # Flush each chunk's pending writes so SA can release intermediate
            # state. Single outer transaction preserved for atomicity.
            s.flush()

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
            now = utcnow_naive()
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

        # Retention prune (spec §4.5): keep inactive jobs for `retention_days`
        # AFTER they last appeared upstream, then drop. Keyed on `last_seen_at`
        # so retention is independent of upstream `posted_date` quality (some
        # ATSes omit it; old prune wiped those rows the instant they went
        # inactive). The just-marked-inactive UPDATE above sets is_active=False
        # but leaves last_seen_at at the *previous* run's started_at, so a job
        # only gets deleted here once that previous run is itself older than
        # `retention_days`.
        cutoff = utcnow_naive() - timedelta(days=settings.retention_days)
        s.execute(
            delete(Job).where(
                and_(
                    Job.is_active.is_(False),
                    Job.last_seen_at < cutoff,
                )
            )
        )

        run = s.get(ScrapeRun, run_id)
        if run is not None:
            run.finished_at = utcnow_naive()
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

    # Reclaim WAL bytes and update SQLite planner stats after a writer-heavy
    # run. Non-fatal if the connection is busy; the auto-checkpoint will pick
    # up later writes anyway. `optimize` is a one-shot statistics refresh that
    # benefits the planner for subsequent reads.
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.exec_driver_sql("PRAGMA optimize")
    except Exception:  # noqa: BLE001 — ops housekeeping, never abort a run
        logger.exception("WAL checkpoint/optimize after _finalize_run failed (non-fatal)")


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
            .execution_options(yield_per=500)
        )
        # Stream rows in chunks so memory stays bounded even on a 10k-row delta.
        for job, company_name in s.execute(stmt):
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
