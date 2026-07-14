"""JobPulse single CLI entrypoint.

Usage:
    python run.py migrate
    python run.py seed
    python run.py scrape [--company NAME] [--ats greenhouse] [--since 2026-05-01] [--no-playwright]
    python run.py serve
    python run.py add-company URL [--name NAME]
    python run.py reset       (drops + recreates the SQLite schema)
"""
from __future__ import annotations

import sys

import typer
from loguru import logger

app = typer.Typer(add_completion=False, no_args_is_help=True, help="JobPulse CLI")


@app.command()
def migrate() -> None:
    """Apply all pending Alembic migrations."""
    from backend.migrations import upgrade_to_head

    upgrade_to_head()
    typer.echo("Migrations applied.")


@app.command()
def seed() -> None:
    """Load seeds/companies.json into SQLite (idempotent)."""
    from backend.seed import run_seed

    inserted = run_seed()
    typer.echo(f"Seed complete. {inserted} new company rows inserted.")


@app.command()
def scrape(
    company: str | None = typer.Option(None, "--company", help="Scrape only one company by id or name."),
    ats: str | None = typer.Option(None, "--ats", help="Restrict to one ATS family."),
    since: str | None = typer.Option(None, "--since", help="Override 15-day filter (YYYY-MM-DD)."),
    no_playwright: bool = typer.Option(False, "--no-playwright", help="Skip JS-rendered sites."),
) -> None:
    """Scrape all active companies (or a subset). Manual trigger — no scheduler."""
    from backend.scrape import run_scrape

    run_scrape(company=company, ats=ats, since=since, no_playwright=no_playwright)


@app.command()
def serve() -> None:
    """Start FastAPI on 127.0.0.1:8000 (serves built frontend if present)."""
    from backend.serve import run_serve

    run_serve()


@app.command("add-company")
def add_company_cmd(
    url: str = typer.Argument(..., help="Careers URL"),
    name: str | None = typer.Option(None, "--name", "-n", help="Display name"),
    ats: str | None = typer.Option(None, "--ats", help="Override detected ATS (e.g. greenhouse)"),
    identifier: str | None = typer.Option(None, "--identifier", help="Override detected ATS identifier"),
) -> None:
    """Register a new company. ATS is auto-detected from the URL when possible."""
    from backend.add_company import add_company

    cid = add_company(url=url, name=name, ats=ats, identifier=identifier)
    typer.echo(f"Company id: {cid}")


@app.command("check-seeds")
def check_seeds_cmd(
    ats: str | None = typer.Option(None, "--ats", help="Restrict to one ATS family."),
    timeout: float = typer.Option(12.0, "--timeout", help="Per-request timeout (s)."),
) -> None:
    """HEAD-probe every careers URL in seeds/companies.json. Writes data/seed_check.csv."""
    from backend.seed_check import check_seeds

    bad = check_seeds(ats=ats, timeout=timeout)
    if bad:
        raise typer.Exit(code=1)


@app.command("heal-seeds")
def heal_seeds_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only; don't modify seeds."),
    min_ok: int | None = typer.Option(None, "--min-ok", help="Exit non-zero if fewer than N companies end up OK."),
) -> None:
    """Live-probe seeds and re-point stale boards to their current ATS.

    Writes verified fixes back to seeds/companies.json and an audit trail to
    data/heal_report.csv. Candidates whose employer name can't be corroborated
    are reported as 'needs-review' rather than auto-applied.
    """
    import asyncio

    from scripts.heal_seeds import run_heal

    code = asyncio.run(run_heal(dry_run=dry_run, min_ok=min_ok))
    raise typer.Exit(code=code)


@app.command("ingest-india")
def ingest_india_cmd(
    from_excel: str | None = typer.Option(
        None, "--from-excel", help="Path to the GoodFirms .xlsx (default: dataset_goodfirms*.xlsx in repo root)."
    ),
    no_excel: bool = typer.Option(False, "--no-excel", help="Skip the Excel source."),
    no_curated: bool = typer.Option(False, "--no-curated", help="Skip the curated JSON source."),
    from_goodfirms: str | None = typer.Option(
        None, "--from-goodfirms", help="Live-scrape GoodFirms directories: 'all' or a comma list (needs Playwright)."
    ),
    goodfirms_pages: int = typer.Option(15, "--goodfirms-pages", help="Max pages per GoodFirms category."),
    max_workers: int = typer.Option(10, "--max-workers", help="Concurrent discovery/sanity workers."),
    sanity_rounds: int = typer.Option(5, "--sanity-rounds", help="HTTP sanity-check attempts per company."),
    sanity_spacing: float = typer.Option(2.0, "--sanity-spacing", help="Seconds between sanity attempts."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only; don't modify seeds."),
) -> None:
    """Ingest India-based tech companies (Excel + curated + optional GoodFirms) into seeds.

    Discovers each company's careers URL / ATS, runs a 5x HTTP sanity check
    (dropping any company that fails all attempts), and merges survivors into
    seeds/companies.json tagged with country="India". Writes audit trails to
    data/india_ingest_report.csv and data/india_ingest_dropped.csv.
    """
    import asyncio
    from pathlib import Path

    from scripts.ingest_india import _default_excel_path, _parse_goodfirms_arg, run_ingest

    excel_path: Path | None = None
    if not no_excel:
        excel_path = Path(from_excel) if from_excel else _default_excel_path()

    code = asyncio.run(
        run_ingest(
            from_excel=excel_path,
            goodfirms_categories=_parse_goodfirms_arg(from_goodfirms),
            from_curated=not no_curated,
            dry_run=dry_run,
            max_workers=max_workers,
            sanity_rounds=sanity_rounds,
            sanity_spacing_s=sanity_spacing,
            goodfirms_pages=goodfirms_pages,
        )
    )
    raise typer.Exit(code=code)


@app.command("infer-selectors")
def infer_selectors_cmd(
    all_custom: bool = typer.Option(False, "--all-custom", help="Process every custom company, not just one country."),
    country: str = typer.Option("India", "--country", help="Restrict to this country (ignored with --all-custom)."),
    playwright: bool = typer.Option(False, "--playwright", help="Enable Playwright fallback for JS-rendered pages."),
    max_playwright: int = typer.Option(80, "--max-playwright", help="Cap the number of Playwright renders."),
    max_workers: int = typer.Option(16, "--max-workers", help="Concurrent httpx workers."),
    refresh: bool = typer.Option(False, "--refresh", help="Re-infer companies that already have selectors."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only; don't modify seeds."),
) -> None:
    """Auto-infer custom_selectors for custom-adapter companies that lack them.

    Fetches each careers page, infers a working (list_item, title, apply_url)
    selector spec (validated against the real extraction engine), and applies it
    to seeds/companies.json. JS-rendered pages matched via Playwright are stored
    as ats_type="playwright". Companies that can't be inferred are written to
    data/selectors_review.csv for manual configuration.
    """
    import asyncio

    from scripts.infer_selectors import run_infer

    code = asyncio.run(
        run_infer(
            all_custom=all_custom,
            country=None if all_custom else country,
            use_playwright=playwright,
            max_playwright=max_playwright,
            max_workers=max_workers,
            dry_run=dry_run,
            refresh=refresh,
        )
    )
    raise typer.Exit(code=code)


@app.command("cleanup-jobs")
def cleanup_jobs_cmd(
    days: int = typer.Option(30, "--days", help="Delete jobs whose last_seen_at is older than this many days."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would be deleted without touching the DB."),
    yes: bool = typer.Option(False, "--yes", help="Skip the interactive confirmation prompt."),
) -> None:
    """Delete jobs that haven't been seen for `days` (default 30) days.

    Uses `last_seen_at` (bumped on every successful scrape) so a job that
    keeps reappearing in the source's careers page is refreshed and never
    removed.
    """
    from scripts.cleanup_jobs import run_cleanup

    if not dry_run and not yes:
        typer.confirm(
            f"Delete jobs older than {days} days? This can't be undone.",
            abort=True,
        )

    summary = run_cleanup(days=days, dry_run=dry_run)
    if summary.dry_run:
        typer.echo(f"Preview: {summary.matched} jobs are older than the {days}-day cutoff.")
    else:
        typer.echo(f"Deleted {summary.deleted} of {summary.matched} matching jobs.")


@app.command("prune-failing")
def prune_failing_cmd(
    threshold: int = typer.Option(5, "--threshold", help="Minimum consecutive_failures to prune."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would be pruned; don't modify anything."),
    no_seed_sync: bool = typer.Option(
        False,
        "--no-seed-sync",
        help="Keep the removed companies inside seeds/companies.json (default: strip them).",
    ),
    yes: bool = typer.Option(False, "--yes", help="Skip the interactive confirmation prompt."),
) -> None:
    """Delete companies whose consecutive_failures >= threshold.

    Jobs and per-run scrape_run_companies rows are removed via FK cascade.
    By default the seed file is rewritten so `python run.py seed` won't
    resurrect the pruned entries; pass --no-seed-sync to keep them.
    """
    from scripts.prune_failing import format_report, run_prune

    if not dry_run and not yes:
        typer.confirm(
            f"Delete every company with consecutive_failures >= {threshold}? "
            "This cascades to their jobs and run history.",
            abort=True,
        )

    summary = run_prune(
        threshold=threshold, dry_run=dry_run, seed_sync=not no_seed_sync
    )
    typer.echo(format_report(summary))


@app.command()
def reset(
    yes: bool = typer.Option(False, "--yes", help="Confirm destructive reset."),
) -> None:
    """Drop ALL schema and re-create from migrations. Destroys all data."""
    if not yes:
        typer.echo("Refusing to reset without --yes. This deletes ALL data.", err=True)
        raise typer.Exit(code=2)
    from backend.migrations import downgrade_to_base, upgrade_to_head

    downgrade_to_base()
    upgrade_to_head()
    typer.echo("DB reset complete.")


def _force_utf8_console() -> None:
    """Ensure stdout/stderr can emit non-ASCII (em dashes, arrows, accents).

    On Windows the console defaults to a legacy code page (cp1252), so log
    lines containing characters like '—' raise UnicodeEncodeError or print as
    '?'. Reconfiguring the streams to UTF-8 (with a safe fallback) fixes every
    such call site at once. No-op on platforms/streams that don't support it.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _configure_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}")


if __name__ == "__main__":
    _force_utf8_console()
    _configure_logging()
    app()
