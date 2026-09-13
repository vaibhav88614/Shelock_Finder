"""Tests for the location facets + sparklines endpoints."""
from __future__ import annotations


def test_sparklines_shape(seeded_db):
    client, _ = seeded_db
    body = client.get("/api/v1/stats/sparklines", params={"days": 14}).json()
    for key in ("new_jobs_per_day", "active_per_day", "runs_jobs_new", "runs_jobs_found"):
        assert key in body
        assert isinstance(body[key], list)

    # Daily series must have exactly `days` points (gap-filled).
    assert len(body["new_jobs_per_day"]) == 14
    assert len(body["active_per_day"]) == 14

    # Each entry has {label, value} with an ISO date label.
    for pt in body["new_jobs_per_day"]:
        assert set(pt.keys()) == {"label", "value"}
        assert len(pt["label"]) == 10  # YYYY-MM-DD

    # Runs list is bounded by the fixture (2 finished runs).
    assert 0 <= len(body["runs_jobs_new"]) <= 2


def test_facets_empty_before_backfill(seeded_db):
    """Before the backfill runs, the structured columns are all NULL and
    every facet list is empty — the endpoint must not crash."""
    client, _ = seeded_db
    body = client.get("/api/v1/stats/facets/locations").json()
    assert body["cities"] == []
    assert body["countries"] == []
    # Remote count comes from the boolean column which defaults to 0.
    assert body["remote"] == 0


def test_sparklines_bounds(seeded_db):
    client, _ = seeded_db
    r = client.get("/api/v1/stats/sparklines", params={"days": 5})
    assert r.status_code == 422  # below min=7
    r = client.get("/api/v1/stats/sparklines", params={"days": 200})
    assert r.status_code == 422  # above max=90
