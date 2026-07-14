"""Tests for the cleanup-jobs + prune-failing scripts and their API surfaces.

Covers three levers:
  * `DELETE /api/v1/jobs/cleanup` — thin HTTP wrapper over `run_cleanup`.
  * `POST /api/v1/companies/bulk-active` — used by the master toggle in the UI.
  * `scripts.prune_failing.run_prune` — CLI-level deletion + seed rewrite.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from backend.adapters.base import fingerprint
from backend.db import session_scope
from backend.models import Company, Job, ScrapeRun, ScrapeRunCompany, utcnow_naive


# ---------------------------------------------------------------------------
# /jobs/cleanup
# ---------------------------------------------------------------------------


def _insert_job(s, company_id: int, ext: str, last_seen_days_ago: int) -> Job:
    now = utcnow_naive()
    j = Job(
        company_id=company_id,
        external_id=ext,
        fingerprint=fingerprint(company_id, ext, "T", None, f"https://x/{ext}"),
        title=f"Job {ext}",
        apply_url=f"https://x/{ext}",
        first_seen_at=now - timedelta(days=last_seen_days_ago + 1),
        last_seen_at=now - timedelta(days=last_seen_days_ago),
    )
    s.add(j)
    return j


def test_cleanup_deletes_stale_jobs(seeded_db):
    """OldCo o1 has last_seen_at ≈ 10min ago; add one 45d old & one 20d old."""
    client, _ = seeded_db

    with session_scope() as s:
        oldco = s.query(Company).filter_by(name="OldCo").one()
        _insert_job(s, oldco.id, "stale-45d", 45)
        _insert_job(s, oldco.id, "stale-20d", 20)

    # Dry-run — nothing deleted.
    r = client.request("DELETE", "/api/v1/jobs/cleanup",
                       params={"days": 30, "dry_run": True})
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["matched"] == 1  # only the 45d-old row
    assert body["deleted"] == 0

    # Real delete.
    r = client.request("DELETE", "/api/v1/jobs/cleanup", params={"days": 30})
    body = r.json()
    assert body["dry_run"] is False
    assert body["deleted"] == 1
    assert body["matched"] == 1

    # Second run: nothing left to prune.
    r = client.request("DELETE", "/api/v1/jobs/cleanup", params={"days": 30})
    assert r.json()["deleted"] == 0


def test_cleanup_script_dry_run(seeded_db):
    """Direct script call — the CLI path used by `python run.py cleanup-jobs`."""
    from scripts.cleanup_jobs import run_cleanup

    client, _ = seeded_db  # noqa: F841  — seeded rows only; use the client to force setup

    with session_scope() as s:
        oldco = s.query(Company).filter_by(name="OldCo").one()
        _insert_job(s, oldco.id, "cli-40d", 40)

    summary = run_cleanup(days=30, dry_run=True)
    assert summary.dry_run
    assert summary.matched == 1
    assert summary.deleted == 0

    with session_scope() as s:
        remaining = s.query(Job).filter_by(external_id="cli-40d").count()
        assert remaining == 1

    summary = run_cleanup(days=30)
    assert summary.deleted == 1


def test_cleanup_rejects_invalid_days(seeded_db):
    client, _ = seeded_db
    r = client.request("DELETE", "/api/v1/jobs/cleanup", params={"days": 0})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# /companies/bulk-active
# ---------------------------------------------------------------------------


def test_bulk_active_by_ids(seeded_db):
    client, _ = seeded_db
    cos = client.get("/api/v1/companies").json()
    ids = [c["id"] for c in cos if c["name"] in {"Stripe", "Netflix"}]

    r = client.post("/api/v1/companies/bulk-active",
                    json={"ids": ids, "active": False})
    assert r.status_code == 200, r.text
    assert r.json() == {"matched": 2, "updated": 2}

    cos_after = client.get("/api/v1/companies").json()
    active_names = {c["name"] for c in cos_after if c["active"]}
    assert active_names == set()

    # Re-run is idempotent — matched stays, updated is 0.
    r = client.post("/api/v1/companies/bulk-active",
                    json={"ids": ids, "active": False})
    assert r.json() == {"matched": 2, "updated": 0}


def test_bulk_active_by_ats_and_failure_ceiling(seeded_db):
    """Master-toggle style filter: standard-ATS families with zero failures."""
    client, _ = seeded_db

    # Force one company into "failing" so it's excluded by the ceiling.
    with session_scope() as s:
        stripe = s.query(Company).filter_by(name="Stripe").one()
        stripe.consecutive_failures = 3

    r = client.post(
        "/api/v1/companies/bulk-active",
        json={
            "active": False,
            "ats_types": ["greenhouse", "lever", "ashby", "workday"],
            "max_consecutive_failures": 0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    # Only Netflix (lever, 0 failures) survives the filter. Stripe is greenhouse
    # but its 3 failures kick it out.
    assert body == {"matched": 1, "updated": 1}

    cos = client.get("/api/v1/companies").json()
    by_name = {c["name"]: c for c in cos}
    assert by_name["Netflix"]["active"] is False
    assert by_name["Stripe"]["active"] is True  # protected by threshold


def test_bulk_active_empty_ids_noop(seeded_db):
    client, _ = seeded_db
    r = client.post("/api/v1/companies/bulk-active",
                    json={"ids": [], "active": True})
    assert r.json() == {"matched": 0, "updated": 0}


# ---------------------------------------------------------------------------
# scripts.prune_failing.run_prune
# ---------------------------------------------------------------------------


def test_prune_removes_failing_and_cascades(seeded_db, tmp_path, monkeypatch):
    """Prune drops the company row + cascades to jobs + scrape_run_companies.

    The seeds file rewrite is redirected to a temp dir so the test doesn't
    mutate the real repo seed.
    """
    from backend import config
    import backend.seed as seed_mod
    import scripts.prune_failing as prune_mod

    client, settings_ = seeded_db

    # Redirect seeds/companies.json into tmp_path so the rewrite is contained.
    seed_dir = tmp_path / "seeds"
    seed_dir.mkdir()
    seed_file = seed_dir / "companies.json"
    seed_file.write_text(
        json.dumps(
            [
                {"name": "Stripe", "careers_url": "https://boards.greenhouse.io/stripe"},
                {"name": "Netflix", "careers_url": "https://jobs.lever.co/netflix"},
                {"name": "OldCo", "careers_url": "https://example.com/jobs"},
            ]
        )
    )
    import dataclasses

    new_settings = dataclasses.replace(settings_, seeds_dir=seed_dir)
    monkeypatch.setattr(config, "settings", new_settings)
    monkeypatch.setattr(prune_mod, "settings", new_settings)
    monkeypatch.setattr(seed_mod, "settings", new_settings)

    # Push OldCo above the threshold and give it a scrape_run link so we can
    # observe the FK cascade.
    with session_scope() as s:
        oldco = s.query(Company).filter_by(name="OldCo").one()
        oldco.consecutive_failures = 7
        run = s.query(ScrapeRun).first()
        s.add(
            ScrapeRunCompany(
                scrape_run_id=run.id,
                company_id=oldco.id,
                status="failed",
                error_message="stale",
            )
        )
        oldco_id = oldco.id

    with session_scope() as s:
        pre_links = s.query(ScrapeRunCompany).filter_by(company_id=oldco_id).count()
        assert pre_links == 1

    # Dry run first.
    summary = prune_mod.run_prune(threshold=5, dry_run=True)
    assert summary.matched == 1
    assert "OldCo" in summary.company_names_removed
    # Nothing actually deleted.
    with session_scope() as s:
        assert s.query(Company).filter_by(id=oldco_id).one_or_none() is not None

    # Wet run.
    summary = prune_mod.run_prune(threshold=5)
    assert summary.matched == 1
    assert summary.company_names_removed == ["OldCo"]
    assert summary.run_links_removed == 1
    assert summary.seeds_removed == 1

    with session_scope() as s:
        assert s.query(Company).filter_by(id=oldco_id).one_or_none() is None
        assert s.query(ScrapeRunCompany).filter_by(company_id=oldco_id).count() == 0
        assert s.query(Job).filter_by(company_id=oldco_id).count() == 0

    # Seed file was rewritten (OldCo removed).
    with seed_file.open() as fh:
        left = json.load(fh)
    assert {r["name"] for r in left} == {"Stripe", "Netflix"}

    # Also confirm the API sees the company gone.
    cos = client.get("/api/v1/companies").json()
    remaining_names = {c["name"] for c in cos}
    assert "OldCo" not in remaining_names
    assert {"Stripe", "Netflix"} <= remaining_names


def test_prune_below_threshold_is_noop(seeded_db):
    from scripts.prune_failing import run_prune

    client, _ = seeded_db
    pre = {c["name"] for c in client.get("/api/v1/companies").json()}

    summary = run_prune(threshold=5, seed_sync=False)
    assert summary.matched == 0
    assert summary.company_ids_removed == []

    post = {c["name"] for c in client.get("/api/v1/companies").json()}
    assert pre == post


def test_prune_rejects_bad_threshold():
    from scripts.prune_failing import run_prune

    with pytest.raises(ValueError):
        run_prune(threshold=0)


# ---------------------------------------------------------------------------
# /jobs offset pagination
# ---------------------------------------------------------------------------


def test_jobs_offset_pagination(seeded_db):
    client, _ = seeded_db

    page1 = client.get("/api/v1/jobs", params={
        "limit": 3, "offset": 0, "include_total": True, "sort": "posted_date"
    }).json()
    assert page1["total"] == 6
    assert len(page1["items"]) == 3
    # offset mode doesn't populate next_cursor — the client uses offset math.
    assert page1["next_cursor"] is None

    page2 = client.get("/api/v1/jobs", params={
        "limit": 3, "offset": 3, "include_total": True, "sort": "posted_date"
    }).json()
    assert page2["total"] == 6
    assert len(page2["items"]) == 3

    ids_1 = {j["id"] for j in page1["items"]}
    ids_2 = {j["id"] for j in page2["items"]}
    assert ids_1.isdisjoint(ids_2)


def test_jobs_offset_and_cursor_conflict(seeded_db):
    client, _ = seeded_db
    r = client.get("/api/v1/jobs", params={"offset": 0, "cursor": "abc"})
    assert r.status_code == 400
    assert "offset" in r.json()["detail"] or "cursor" in r.json()["detail"]
