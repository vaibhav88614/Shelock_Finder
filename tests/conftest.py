"""Shared pytest fixtures."""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    """Return a callable `loader(name)` that reads tests/fixtures/<name>."""

    def _loader(name: str):
        path = FIXTURES_DIR / name
        with path.open("r", encoding="utf-8") as fh:
            if path.suffix == ".json":
                return json.load(fh)
            return fh.read()

    return _loader


@pytest.fixture
def fake_company():
    """A duck-typed stand-in for the SQLAlchemy `Company` model.

    Adapters only read `name`, `ats_identifier`, `ats_type`, and `careers_url`
    so we keep tests free of DB setup.
    """

    def _make(
        *,
        id: int = 1,
        name: str = "Test Co",
        ats_type: str = "greenhouse",
        ats_identifier: str = "testco",
        careers_url: str = "https://boards.greenhouse.io/testco",
    ):
        return SimpleNamespace(
            id=id,
            name=name,
            ats_type=ats_type,
            ats_identifier=ats_identifier,
            careers_url=careers_url,
        )

    return _make


# ---------------------------------------------------------------------------
# Temp-DB-backed FastAPI TestClient (phase 4+ API tests)
# ---------------------------------------------------------------------------


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    """Bind backend to a fresh SQLite + return a FastAPI TestClient."""
    from fastapi.testclient import TestClient

    from backend import config, db, migrations
    import backend.api.deps as deps_mod
    import backend.scrape as scrape_mod
    import backend.seed as seed_mod
    import backend.serve as serve_mod

    db_path: Path = tmp_path / "api_jobpulse.db"
    data_dir: Path = tmp_path / "data"
    data_dir.mkdir()

    new_settings = dataclasses.replace(
        config.settings, db_path=db_path, data_dir=data_dir, api_key=None
    )
    monkeypatch.setattr(config, "settings", new_settings)
    for mod in (scrape_mod, serve_mod, seed_mod, deps_mod):
        monkeypatch.setattr(mod, "settings", new_settings, raising=False)

    db.rebind(new_settings.db_url)
    migrations.upgrade_to_head()

    app = serve_mod.create_app()
    client = TestClient(app)
    try:
        yield client, new_settings
    finally:
        client.close()
        db.engine.dispose()


@pytest.fixture
def seeded_db(api_env):
    """Seed 3 companies + 8 jobs covering every filter axis used by /jobs tests."""
    from backend.adapters.base import fingerprint
    from backend.db import session_scope
    from backend.models import Company, Job, ScrapeRun

    client, settings_ = api_env
    now = datetime.utcnow()

    with session_scope() as s:
        stripe = Company(
            name="Stripe", careers_url="https://boards.greenhouse.io/stripe",
            ats_type="greenhouse", ats_identifier="stripe", active=True,
        )
        netflix = Company(
            name="Netflix", careers_url="https://jobs.lever.co/netflix",
            ats_type="lever", ats_identifier="netflix", active=True,
        )
        oldco = Company(
            name="OldCo", careers_url="https://example.com/jobs",
            ats_type="custom", active=False,
        )
        s.add_all([stripe, netflix, oldco])
        s.flush()

        run1 = ScrapeRun(
            started_at=now - timedelta(days=3),
            finished_at=now - timedelta(days=3),
            status="ok", companies_scraped=2,
            jobs_found_total=5, jobs_new_total=5,
        )
        run2 = ScrapeRun(
            started_at=now - timedelta(minutes=10),
            finished_at=now - timedelta(minutes=9),
            status="ok", companies_scraped=2,
            jobs_found_total=6, jobs_new_total=1,
        )
        s.add_all([run1, run2])
        s.flush()

        def J(
            company_id, ext, title, location, desc, posted_days_ago,
            exp_min=None, exp_max=None, remote=None, first_seen=None,
            active=True, employment_type=None, department=None,
        ):
            return Job(
                company_id=company_id, external_id=ext,
                fingerprint=fingerprint(company_id, ext, title, location, f"https://x/{ext}"),
                title=title, description=desc, location=location,
                remote_type=remote, department=department,
                employment_type=employment_type,
                experience_min=exp_min, experience_max=exp_max,
                posted_date=now - timedelta(days=posted_days_ago),
                apply_url=f"https://x/{ext}",
                first_seen_at=first_seen or (now - timedelta(days=3)),
                last_seen_at=now - timedelta(minutes=10),
                is_active=active,
            )

        s.add_all([
            # Stripe — 3 jobs
            J(stripe.id, "s1", "Senior Python Engineer", "San Francisco, CA",
              "Build payments with Python and PostgreSQL. 5-8 years experience.",
              posted_days_ago=2, exp_min=5, exp_max=8, department="Engineering"),
            J(stripe.id, "s2", "Staff ML Engineer (Remote)", "Remote - US",
              "Machine learning role. Minimum 7 years experience. PyTorch, Python.",
              posted_days_ago=1, exp_min=7, remote="remote", department="ML"),
            J(stripe.id, "s3", "C++ Systems Engineer", "New York, NY",
              "Low-level systems work in C++ and Rust. 3-5 years.",
              posted_days_ago=4, exp_min=3, exp_max=5, department="Infra"),

            # Netflix — 3 jobs, n3 is "new in last run"
            J(netflix.id, "n1", "Senior React Engineer", "Los Gatos, CA",
              "Build the Netflix web UI with React and TypeScript.",
              posted_days_ago=2, exp_min=4, exp_max=7, department="Frontend"),
            J(netflix.id, "n2", "Data Scientist", "Remote - Worldwide",
              "Recommendation models with Python. 3-5 years.",
              posted_days_ago=5, exp_min=3, exp_max=5, remote="remote",
              department="Data"),
            J(netflix.id, "n3", "Junior Engineer (NEW)", "Los Gatos, CA",
              "Entry-level role. No prior experience required.",
              posted_days_ago=0, first_seen=run2.started_at,
              department="Engineering"),

            # OldCo — one inactive, one too-old (must be excluded by default)
            J(oldco.id, "o1", "Stale Job", "Boston, MA",
              "Old posting, no longer live.", posted_days_ago=2, active=False),
            J(oldco.id, "o2", "Ancient Job", "Boston, MA",
              "Posted 30 days ago.", posted_days_ago=30, exp_min=1),
        ])

    return client, settings_
