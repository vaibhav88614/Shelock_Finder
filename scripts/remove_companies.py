"""Hard-delete companies by name (cascades to jobs + run history).

    python run.py remove-companies                  # built-in req.txt removal list
    python run.py remove-companies "ValueCoders"    # specific names
    python run.py remove-companies --dry-run

Matching is case-insensitive on the trimmed company name. Jobs
(FK -> companies.id ON DELETE CASCADE) and scrape_run_companies rows are
removed automatically. Matching entries are also stripped from
`seeds/companies.json` (timestamped .bak) so `python run.py seed` won't
resurrect them; that step is a no-op if the entries were already removed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger
from sqlalchemy import func, select

from backend.db import session_scope
from backend.migrations import upgrade_to_head
from backend.models import Company, ScrapeRunCompany
from scripts.prune_failing import _rewrite_seed_file


# Exact names as stored in seeds/companies.json (see req.txt).
DEFAULT_REMOVE: tuple[str, ...] = (
    "ValueCoders",
    "Unified Infotech",
    "Spiral Mantra Private Limited",
    "Polestar",
    "Polestar Tech Consultancy",
)


@dataclass
class RemoveSummary:
    requested: list[str]
    matched: int = 0
    company_ids_removed: list[int] = field(default_factory=list)
    company_names_removed: list[str] = field(default_factory=list)
    run_links_removed: int = 0
    seeds_removed: int = 0
    dry_run: bool = False


def run_remove(
    names: list[str] | None = None,
    *,
    dry_run: bool = False,
    seed_sync: bool = True,
) -> RemoveSummary:
    """Delete every company whose name matches one of `names` (case-insensitive)."""
    requested = list(names) if names else list(DEFAULT_REMOVE)
    wanted = {n.strip().casefold() for n in requested}

    upgrade_to_head()
    summary = RemoveSummary(requested=requested, dry_run=dry_run)

    with session_scope() as s:
        rows = [
            c
            for c in s.scalars(select(Company))
            if (c.name or "").strip().casefold() in wanted
        ]
        summary.matched = len(rows)
        if not rows:
            logger.info("remove-companies: no matching companies found.")
            return summary

        summary.company_ids_removed = [c.id for c in rows]
        summary.company_names_removed = [c.name for c in rows]
        summary.run_links_removed = int(
            s.scalar(
                select(func.count())
                .select_from(ScrapeRunCompany)
                .where(ScrapeRunCompany.company_id.in_(summary.company_ids_removed))
            )
            or 0
        )

        for c in rows:
            logger.info("  - {name} (id={id}, ats={ats})", name=c.name, id=c.id, ats=c.ats_type)

        if not dry_run:
            for c in rows:  # FK ON DELETE CASCADE removes jobs + scrape_run_companies
                s.delete(c)

    if seed_sync:
        summary.seeds_removed = _rewrite_seed_file(
            set(summary.company_names_removed), dry_run=dry_run
        )

    return summary


def format_report(summary: RemoveSummary) -> str:
    """Return a compact multi-line human report suitable for CLI echo."""
    verb = "Would delete" if summary.dry_run else "Deleted"
    lines = [
        f"{verb} {summary.matched} companies (requested {len(summary.requested)}).",
        f"  scrape_run_companies rows cascaded: {summary.run_links_removed}",
        f"  seeds/companies.json entries touched: {summary.seeds_removed}",
    ]
    if summary.company_names_removed:
        lines.append("  companies:")
        lines.extend(f"    - {n}" for n in summary.company_names_removed)
    removed = {n.strip().casefold() for n in summary.company_names_removed}
    not_found = [n for n in summary.requested if n.strip().casefold() not in removed]
    if not_found:
        lines.append("  not found (already absent):")
        lines.extend(f"    - {n}" for n in not_found)
    return "\n".join(lines)
