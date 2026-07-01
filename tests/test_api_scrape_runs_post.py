"""POST /api/v1/scrape-runs endpoint tests.

Covers the dashboard-triggered scrape entry point that the existing API test
file doesn't touch:

  - 202 + queued response on success.
  - 409 when another run has `finished_at IS NULL`.
  - Query-param passthrough for `ats` and `no_playwright`.
"""
from __future__ import annotations

import pytest


def _no_op_run_scrape(*args, **kwargs):
    """Replace `run_scrape` so the FastAPI BackgroundTask doesn't actually scrape."""
    return 0


def test_post_scrape_runs_returns_202(api_env, monkeypatch):
    client, _ = api_env
    monkeypatch.setattr("backend.scrape.run_scrape", _no_op_run_scrape)
    r = client.post("/api/v1/scrape-runs")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["ats"] is None
    assert body["no_playwright"] is False


def test_post_scrape_runs_passes_through_query_params(api_env, monkeypatch):
    client, _ = api_env
    monkeypatch.setattr("backend.scrape.run_scrape", _no_op_run_scrape)
    r = client.post("/api/v1/scrape-runs?ats=greenhouse&no_playwright=true")
    assert r.status_code == 202
    body = r.json()
    assert body["ats"] == "greenhouse"
    assert body["no_playwright"] is True


def test_post_scrape_runs_409_when_in_flight(api_env, monkeypatch):
    """A second POST while another run has finished_at IS NULL must 409."""
    client, _ = api_env
    monkeypatch.setattr("backend.scrape.run_scrape", _no_op_run_scrape)

    from backend.db import session_scope
    from backend.models import ScrapeRun, utcnow_naive

    with session_scope() as s:
        s.add(
            ScrapeRun(
                started_at=utcnow_naive(),
                finished_at=None,  # in-flight
                status="running",
            )
        )

    r = client.post("/api/v1/scrape-runs")
    assert r.status_code == 409
    assert "in-flight" in r.json()["detail"].lower()


def test_post_scrape_runs_allows_new_when_previous_finished(api_env, monkeypatch):
    """A finished run must not block a fresh POST."""
    client, _ = api_env
    monkeypatch.setattr("backend.scrape.run_scrape", _no_op_run_scrape)

    from backend.db import session_scope
    from backend.models import ScrapeRun, utcnow_naive

    now = utcnow_naive()
    with session_scope() as s:
        s.add(
            ScrapeRun(
                started_at=now,
                finished_at=now,  # done
                status="ok",
            )
        )

    r = client.post("/api/v1/scrape-runs")
    assert r.status_code == 202
