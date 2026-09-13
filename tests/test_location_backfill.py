"""End-to-end tests for the location backfill script + facet endpoint.

Relies on the ``seeded_db`` fixture which inserts 8 jobs with a mix of
locations (SF, remote, "Los Gatos", "Boston" etc.). The backfill parses
those into structured columns; the facets endpoint counts them.
"""
from __future__ import annotations

from datetime import timedelta

from backend.adapters.base import fingerprint
from backend.db import session_scope
from backend.models import Company, Job, utcnow_naive


def test_facets_endpoint_after_backfill(seeded_db):
    """Backfill the seed rows then verify facet counts + structured filters."""
    from scripts.backfill_locations import run_backfill

    client, _ = seeded_db

    # Add a couple of India-tagged jobs so the country facet has >1 bucket.
    with session_scope() as s:
        stripe = s.query(Company).filter_by(name="Stripe").one()
        stripe.country = "United States"
        now = utcnow_naive()
        for ext, loc in [
            ("in-1", "Bengaluru, India"),
            ("in-2", "Bombay, India"),  # alias — should canonicalize to Mumbai
        ]:
            s.add(
                Job(
                    company_id=stripe.id,
                    external_id=ext,
                    fingerprint=fingerprint(stripe.id, ext, "Engineer", loc, f"https://x/{ext}"),
                    title="Engineer",
                    apply_url=f"https://x/{ext}",
                    location=loc,
                    posted_date=now - timedelta(days=2),
                    first_seen_at=now - timedelta(days=2),
                    last_seen_at=now - timedelta(minutes=10),
                    is_active=True,
                )
            )

    summary = run_backfill()
    assert summary.processed >= 10   # 8 seeded + 2 India inserts
    assert summary.updated >= 5      # at least the geo-locatable rows

    facets = client.get(
        "/api/v1/stats/facets/locations", params={"posted_within_days": 15}
    ).json()

    country_map = {row["value"]: row["count"] for row in facets["countries"]}
    # Both new India rows should be counted; the seeded Boston / SF / LA
    # rows land under United States.
    assert country_map.get("India", 0) >= 2
    assert country_map.get("United States", 0) >= 1

    city_map = {row["value"]: row["count"] for row in facets["cities"]}
    # Alias got canonicalised.
    assert "Mumbai" in city_map
    assert "Bombay" not in city_map

    # Sanity: remote count matches the number of `remote_type == "remote"`
    # seed rows (s2 + n2).
    assert facets["remote"] >= 2


def test_structured_location_filter(seeded_db):
    """`countries=India` and `cities=Mumbai` should filter the /jobs list."""
    from scripts.backfill_locations import run_backfill

    client, _ = seeded_db

    with session_scope() as s:
        netflix = s.query(Company).filter_by(name="Netflix").one()
        now = utcnow_naive()
        s.add(
            Job(
                company_id=netflix.id,
                external_id="in-only",
                fingerprint=fingerprint(netflix.id, "in-only", "Backend", "Mumbai, India",
                                         "https://x/in-only"),
                title="Backend Engineer (India)",
                apply_url="https://x/in-only",
                location="Mumbai, India",
                posted_date=now - timedelta(days=1),
                first_seen_at=now - timedelta(days=1),
                last_seen_at=now - timedelta(minutes=10),
                is_active=True,
            )
        )
    run_backfill()

    # countries filter
    body = client.get(
        "/api/v1/jobs", params={"countries": ["India"], "include_total": True}
    ).json()
    titles = {j["title"] for j in body["items"]}
    assert "Backend Engineer (India)" in titles
    # US-only titles must NOT come back.
    assert "Senior Python Engineer" not in titles

    # cities filter
    body2 = client.get("/api/v1/jobs", params={"cities": ["Mumbai"]}).json()
    assert any(j["city"] == "Mumbai" for j in body2["items"])
