"""Delete jobs whose `last_seen_at` is older than a cutoff.

Callable from the CLI:
    python run.py cleanup-jobs                 # deletes anything >30 days old
    python run.py cleanup-jobs --days 45
    python run.py cleanup-jobs --dry-run

Uses `last_seen_at` (bumped on every successful scrape) so a job that keeps
reappearing on a careers page is refreshed — this removes truly stale rows.

Also mirrors the survivors back to `seeds/companies.json` — no; seeds hold
company metadata only, not per-job history, so nothing needs to be touched
there.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import delete, func, select

from backend.db import session_scope
from backend.migrations import upgrade_to_head
from backend.models import Job, utcnow_naive


@dataclass
class CleanupSummary:
    cutoff: datetime
    matched: int
    deleted: int
    dry_run: bool


def run_cleanup(days: int = 30, *, dry_run: bool = False) -> CleanupSummary:
    """Delete every Job with `last_seen_at < now - days`.

    Rows deleted are gone permanently — the caller should confirm before
    running with `dry_run=False`.
    """
    if days < 1:
        raise ValueError("days must be >= 1")

    upgrade_to_head()
    cutoff = utcnow_naive() - timedelta(days=days)

    with session_scope() as s:
        matched = int(
            s.scalar(
                select(func.count()).select_from(Job).where(Job.last_seen_at < cutoff)
            )
            or 0
        )
        deleted = 0
        if not dry_run and matched > 0:
            result = s.execute(delete(Job).where(Job.last_seen_at < cutoff))
            deleted = int(result.rowcount or 0)

    logger.info(
        "cleanup-jobs: cutoff={cutoff:%Y-%m-%d %H:%M} matched={matched} deleted={deleted} dry_run={dry_run}",
        cutoff=cutoff,
        matched=matched,
        deleted=deleted,
        dry_run=dry_run,
    )
    return CleanupSummary(cutoff=cutoff, matched=matched, deleted=deleted, dry_run=dry_run)
