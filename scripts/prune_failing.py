"""Delete companies whose consecutive_failures has crossed a threshold.

    python run.py prune-failing                   # threshold=5 by default
    python run.py prune-failing --threshold 3
    python run.py prune-failing --dry-run
    python run.py prune-failing --no-seed-sync    # keep the seed file entry

Cascade behaviour (see `backend/models.py`):
  * Jobs FK -> companies.id ON DELETE CASCADE       -> jobs get removed
  * scrape_run_companies FK -> companies.id CASCADE -> per-run history purged

The ScrapeRun *summary* rows themselves stay untouched — their
`companies_scraped` / `jobs_found_total` are historical counters and don't
per-company-decompose after the fact. Only the `scrape_run_companies` link
table gets pruned, which is what the user asked for ("remove the companies
from runs which have 5 fails").

By default the removed companies are also stripped from `seeds/companies.json`
so a subsequent `python run.py seed` won't resurrect them.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db import session_scope
from backend.migrations import upgrade_to_head
from backend.models import Company, ScrapeRunCompany, utcnow_naive


@dataclass
class PruneSummary:
    threshold: int
    matched: int  # companies at or above threshold
    company_ids_removed: list[int] = field(default_factory=list)
    company_names_removed: list[str] = field(default_factory=list)
    run_links_removed: int = 0
    seeds_removed: int = 0
    dry_run: bool = False


def _count_run_links(s: Session, company_ids: list[int]) -> int:
    if not company_ids:
        return 0
    return int(
        s.scalar(
            select(func.count())
            .select_from(ScrapeRunCompany)
            .where(ScrapeRunCompany.company_id.in_(company_ids))
        )
        or 0
    )


def _rewrite_seed_file(names_to_drop: set[str], *, dry_run: bool) -> int:
    """Rewrite `seeds/companies.json` without the pruned company entries.

    Returns the number of seed rows dropped. A timestamped `.bak` is made
    before the rewrite so an operator can restore if the CLI was invoked
    accidentally.
    """
    path: Path = settings.seeds_dir / "companies.json"
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"Seed file {path} must contain a JSON array")

    kept: list[dict] = []
    dropped = 0
    for row in data:
        if isinstance(row, dict) and row.get("name") in names_to_drop:
            dropped += 1
            continue
        kept.append(row)

    if dropped and not dry_run:
        stamp = utcnow_naive().strftime("%Y%m%d_%H%M%S")
        backup = path.with_suffix(f".json.bak.{stamp}")
        shutil.copy2(path, backup)
        logger.info("Seed backup written to {}", backup)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(kept, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    return dropped


def run_prune(
    threshold: int = 5,
    *,
    dry_run: bool = False,
    seed_sync: bool = True,
) -> PruneSummary:
    """Remove companies at or above `threshold` consecutive failures.

    Args:
        threshold: minimum `consecutive_failures` for a company to be pruned.
        dry_run: when True, only reports what would happen.
        seed_sync: when True (default), removes matching rows from
            `seeds/companies.json` so re-seeding won't reintroduce them.
    """
    if threshold < 1:
        raise ValueError("threshold must be >= 1")

    upgrade_to_head()
    summary = PruneSummary(threshold=threshold, matched=0, dry_run=dry_run)

    with session_scope() as s:
        rows = list(
            s.scalars(
                select(Company)
                .where(Company.consecutive_failures >= threshold)
                .order_by(Company.consecutive_failures.desc(), Company.name)
            )
        )
        summary.matched = len(rows)
        if not rows:
            logger.info("prune-failing: no companies at or above threshold={} — nothing to do.", threshold)
            return summary

        summary.company_ids_removed = [c.id for c in rows]
        summary.company_names_removed = [c.name for c in rows]

        summary.run_links_removed = _count_run_links(s, summary.company_ids_removed)

        logger.info(
            "prune-failing: {n} companies match threshold={t} — {links} scrape_run_companies links will cascade.",
            n=len(rows),
            t=threshold,
            links=summary.run_links_removed,
        )
        for c in rows:
            logger.info("  - {name} (id={id}, ats={ats}, fails={fails})",
                        name=c.name, id=c.id, ats=c.ats_type, fails=c.consecutive_failures)

        if not dry_run:
            # Rely on FK ON DELETE CASCADE for jobs + scrape_run_companies.
            for c in rows:
                s.delete(c)

    if seed_sync:
        summary.seeds_removed = _rewrite_seed_file(
            set(summary.company_names_removed), dry_run=dry_run
        )
        logger.info(
            "prune-failing: {n} entries {verb} in seeds/companies.json.",
            n=summary.seeds_removed,
            verb="would be removed" if dry_run else "removed",
        )

    return summary


def format_report(summary: PruneSummary) -> str:
    """Return a compact multi-line human report suitable for CLI echo."""
    verb = "Would delete" if summary.dry_run else "Deleted"
    lines = [
        f"{verb} {summary.matched} companies at threshold >= {summary.threshold}.",
        f"  scrape_run_companies rows to cascade: {summary.run_links_removed}",
        f"  seeds/companies.json entries touched: {summary.seeds_removed}",
    ]
    if summary.company_names_removed:
        lines.append("  companies:")
        for n in summary.company_names_removed:
            lines.append(f"    - {n}")
    return "\n".join(lines)
