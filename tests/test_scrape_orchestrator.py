"""End-to-end scrape orchestrator test.

Uses a fresh temp SQLite DB (via `backend.db.rebind`), real Alembic migrations,
real adapters, and `respx`-mocked Greenhouse + Lever endpoints. Verifies:

  - Run #1 inserts all jobs, writes a delta CSV with N rows.
  - Run #2 (same HTTP responses) inserts 0 new jobs, writes a delta CSV with 0 rows.
  - Run #3 (one job removed upstream) marks the missing job inactive.
  - Per-company failure (404) does not abort the whole run, bumps the
    consecutive_failures counter, and records a failed ScrapeRunCompany row.
"""
from __future__ import annotations

import csv
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Bind the backend to a fresh SQLite file under tmp_path and migrate it."""
    from backend import config, db, migrations

    db_path: Path = tmp_path / "test_jobpulse.db"
    data_dir: Path = tmp_path / "data"
    data_dir.mkdir()

    # Replace the frozen settings dataclass with one pointing at tmp_path.
    import dataclasses

    new_settings = dataclasses.replace(
        config.settings,
        db_path=db_path,
        data_dir=data_dir,
    )
    monkeypatch.setattr(config, "settings", new_settings)

    # Also patch the `settings` symbols already imported into submodules.
    import backend.scrape as scrape_mod
    import backend.serve as serve_mod
    import backend.seed as seed_mod

    monkeypatch.setattr(scrape_mod, "settings", new_settings)
    monkeypatch.setattr(serve_mod, "settings", new_settings)
    monkeypatch.setattr(seed_mod, "settings", new_settings)

    db.rebind(new_settings.db_url)
    migrations.upgrade_to_head()

    yield new_settings

    db.engine.dispose()


def _seed_companies(stripe_token: str = "teststripe", netflix_slug: str = "testnetflix"):
    from backend.db import session_scope
    from backend.models import Company

    with session_scope() as s:
        s.add(
            Company(
                name="TestStripe",
                careers_url=f"https://boards.greenhouse.io/{stripe_token}",
                ats_type="greenhouse",
                ats_identifier=stripe_token,
                active=True,
            )
        )
        s.add(
            Company(
                name="TestNetflix",
                careers_url=f"https://jobs.lever.co/{netflix_slug}",
                ats_type="lever",
                ats_identifier=netflix_slug,
                active=True,
            )
        )


def _latest_delta_csv(data_dir: Path) -> Path:
    csvs = sorted(data_dir.glob("last_run_new_jobs_*.csv"))
    assert csvs, f"no delta CSV in {data_dir}"
    return csvs[-1]


def _csv_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return max(0, sum(1 for _ in csv.reader(fh)) - 1)  # minus header


def test_scrape_full_dedupe_lifecycle(temp_db, load_fixture, lever_payload_now, stepping_clock):
    """Run #1 ingests 5, run #2 ingests 0, run #3 marks 1 inactive."""
    from backend.db import session_scope
    from backend.models import Company, Job, ScrapeRun, ScrapeRunCompany
    from backend.scrape import run_scrape

    gh_payload = load_fixture("greenhouse_teststripe.json")  # 3 jobs
    lever_payload = lever_payload_now  # 2 jobs with fresh createdAt timestamps

    _seed_companies()

    gh_url = "https://boards-api.greenhouse.io/v1/boards/teststripe/jobs?content=true"
    lv_url = "https://api.lever.co/v0/postings/testnetflix?mode=json"

    # --- Run #1: fresh ----------------------------------------------------
    with respx.mock(assert_all_called=True) as router:
        router.get(gh_url).mock(return_value=httpx.Response(200, json=gh_payload))
        router.get(lv_url).mock(return_value=httpx.Response(200, json=lever_payload))
        run_id_1 = run_scrape()

    assert run_id_1 > 0
    with session_scope() as s:
        run1 = s.get(ScrapeRun, run_id_1)
        assert run1.status == "ok"
        assert run1.companies_scraped == 2
        assert run1.jobs_found_total == 5
        assert run1.jobs_new_total == 5
        all_jobs = s.scalars(select(Job)).all()
        assert len(all_jobs) == 5
        assert all(j.is_active for j in all_jobs)
        # consecutive_failures reset, last_success_at set
        for c in s.scalars(select(Company)):
            assert c.consecutive_failures == 0
            assert c.last_success_at is not None

    csv1 = _latest_delta_csv(temp_db.data_dir)
    assert _csv_row_count(csv1) == 5, "first run's delta CSV must contain all 5 jobs"

    # --- Run #2: same upstream → zero new --------------------------------
    # `stepping_clock` advances `utcnow_naive` per call, so run #2's started_at
    # is already at least 1s after run #1's last call — distinct CSV filename
    # without `time.sleep`.

    with respx.mock(assert_all_called=True) as router:
        router.get(gh_url).mock(return_value=httpx.Response(200, json=gh_payload))
        router.get(lv_url).mock(return_value=httpx.Response(200, json=lever_payload))
        run_id_2 = run_scrape()

    assert run_id_2 != run_id_1
    with session_scope() as s:
        run2 = s.get(ScrapeRun, run_id_2)
        assert run2.status == "ok"
        assert run2.jobs_found_total == 5
        assert run2.jobs_new_total == 0, "no new fingerprints on rerun"
        all_jobs = s.scalars(select(Job)).all()
        assert len(all_jobs) == 5, "no extra rows created"
        assert all(j.is_active for j in all_jobs)

    csvs = sorted(temp_db.data_dir.glob("last_run_new_jobs_*.csv"))
    assert len(csvs) == 2
    csv2 = csvs[-1]
    assert csv2 != csv1
    assert _csv_row_count(csv2) == 0, "second delta CSV must be empty"

    # --- Run #3: one Lever job disappears upstream -----------------------
    shrunk_lever = lever_payload[:1]  # drop the second posting
    with respx.mock(assert_all_called=True) as router:
        router.get(gh_url).mock(return_value=httpx.Response(200, json=gh_payload))
        router.get(lv_url).mock(return_value=httpx.Response(200, json=shrunk_lever))
        run_id_3 = run_scrape()

    with session_scope() as s:
        run3 = s.get(ScrapeRun, run_id_3)
        assert run3.status == "ok"
        assert run3.jobs_new_total == 0
        # The disappeared posting is still in DB (within retention) but inactive.
        inactive = s.scalars(select(Job).where(Job.is_active.is_(False))).all()
        assert len(inactive) == 1
        # Sanity: per-company row recorded ok status
        per = s.scalars(
            select(ScrapeRunCompany).where(ScrapeRunCompany.scrape_run_id == run_id_3)
        ).all()
        assert {p.status for p in per} == {"ok"}


def test_scrape_isolates_per_company_failure(temp_db, load_fixture):
    """A 404 on one company must not affect the other; failure is recorded."""
    from backend.db import session_scope
    from backend.models import Company, ScrapeRun, ScrapeRunCompany
    from backend.scrape import run_scrape

    gh_payload = load_fixture("greenhouse_teststripe.json")
    _seed_companies()

    gh_url = "https://boards-api.greenhouse.io/v1/boards/teststripe/jobs?content=true"
    lv_url = "https://api.lever.co/v0/postings/testnetflix?mode=json"

    with respx.mock(assert_all_called=True) as router:
        router.get(gh_url).mock(return_value=httpx.Response(200, json=gh_payload))
        router.get(lv_url).mock(return_value=httpx.Response(404, text="gone"))
        run_id = run_scrape()

    with session_scope() as s:
        run = s.get(ScrapeRun, run_id)
        assert run.status == "partial"
        assert run.jobs_new_total == 3
        per = {
            p.company_id: p
            for p in s.scalars(
                select(ScrapeRunCompany).where(ScrapeRunCompany.scrape_run_id == run_id)
            )
        }
        # exactly one ok + one failed
        statuses = sorted(p.status for p in per.values())
        assert statuses == ["failed", "ok"]
        failed = next(p for p in per.values() if p.status == "failed")
        assert failed.error_message and "404" in failed.error_message

        # Failing company gets consecutive_failures bumped
        netflix = s.scalar(select(Company).where(Company.name == "TestNetflix"))
        assert netflix.consecutive_failures == 1
        assert netflix.active is True  # still active (under threshold)

        # Successful company's counters reset / set
        stripe = s.scalar(select(Company).where(Company.name == "TestStripe"))
        assert stripe.consecutive_failures == 0
        assert stripe.last_success_at is not None


def test_scrape_filters_by_ats(temp_db, load_fixture):
    """`--ats greenhouse` must only hit Greenhouse companies."""
    from backend.scrape import run_scrape

    gh_payload = load_fixture("greenhouse_teststripe.json")
    _seed_companies()

    gh_url = "https://boards-api.greenhouse.io/v1/boards/teststripe/jobs?content=true"

    with respx.mock(assert_all_called=True) as router:
        router.get(gh_url).mock(return_value=httpx.Response(200, json=gh_payload))
        # No Lever route registered → if scrape hits it, respx raises.
        run_id = run_scrape(ats="greenhouse")

    assert run_id > 0
