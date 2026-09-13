"""One-shot backfill of the structured location columns on `jobs`.

The 0005 migration adds `city`, `region`, `country`, `is_remote`. This script
walks every row in the table, re-parses `location` via
:func:`backend.location.parse_location`, and writes the results.

Idempotent — safe to run repeatedly, and safe to run after schema migrations
even when partial data is already populated.

Usage:
    python run.py backfill-locations                # backfill everything
    python run.py backfill-locations --limit 500    # first 500 rows only
    python run.py backfill-locations --dry-run
"""
from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from sqlalchemy import select

from backend.db import session_scope
from backend.location import parse_location
from backend.migrations import upgrade_to_head
from backend.models import Company, Job


@dataclass
class BackfillSummary:
    processed: int
    updated: int
    with_city: int
    with_country: int
    remote: int
    dry_run: bool


def run_backfill(*, limit: int | None = None, dry_run: bool = False) -> BackfillSummary:
    """Re-parse every job's location string into the structured columns."""
    upgrade_to_head()

    processed = updated = with_city = with_country = remote_count = 0

    with session_scope() as s:
        # Pull (job, company.country) once so the parser can use the country
        # hint without a round-trip per row. Streaming via yield_per keeps
        # memory bounded at 30k rows.
        stmt = (
            select(Job, Company.country)
            .join(Company, Company.id == Job.company_id)
            .execution_options(yield_per=500)
            .order_by(Job.id)
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        for job, company_country in s.execute(stmt):
            processed += 1
            parsed = parse_location(job.location, company_country)
            is_remote = (
                (job.remote_type or "").lower() == "remote" or parsed.is_remote
            )
            # Detect an actual change so we don't dirty the row (and therefore
            # skip the SA UPDATE) when nothing needs to move.
            changed = (
                job.city != parsed.city
                or job.region != parsed.region
                or job.country != parsed.country
                or job.is_remote != is_remote
            )
            if changed and not dry_run:
                job.city = parsed.city
                job.region = parsed.region
                job.country = parsed.country
                job.is_remote = is_remote
            if changed:
                updated += 1
            if parsed.city:
                with_city += 1
            if parsed.country:
                with_country += 1
            if is_remote:
                remote_count += 1
            if processed % 2000 == 0:
                logger.info(
                    "backfill-locations progress: processed={} updated={}",
                    processed,
                    updated,
                )

    logger.info(
        "backfill-locations done: processed={} updated={} city={} country={} remote={} dry_run={}",
        processed,
        updated,
        with_city,
        with_country,
        remote_count,
        dry_run,
    )
    return BackfillSummary(
        processed=processed,
        updated=updated,
        with_city=with_city,
        with_country=with_country,
        remote=remote_count,
        dry_run=dry_run,
    )
