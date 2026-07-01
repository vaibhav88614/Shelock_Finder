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
