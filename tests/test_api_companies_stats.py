"""Tests for /api/v1/companies CRUD + bulk import + /stats + /scrape-runs."""
from __future__ import annotations

import io


def test_list_and_filter_companies(seeded_db):
    client, _ = seeded_db

    all_c = client.get("/api/v1/companies").json()
    assert {c["name"] for c in all_c} == {"Stripe", "Netflix", "OldCo"}

    active = client.get("/api/v1/companies", params={"active": True}).json()
    assert {c["name"] for c in active} == {"Stripe", "Netflix"}

    by_ats = client.get("/api/v1/companies", params={"ats_type": "lever"}).json()
    assert {c["name"] for c in by_ats} == {"Netflix"}


def test_create_company_then_patch_then_delete(api_env):
    client, _ = api_env

    create = client.post("/api/v1/companies", json={
        "name": "Anthropic",
        "careers_url": "https://boards.greenhouse.io/anthropic",
        "ats_type": "greenhouse",
        "ats_identifier": "anthropic",
    })
    assert create.status_code == 201, create.text
    cid = create.json()["id"]
    assert create.json()["ats_type"] == "greenhouse"

    patched = client.patch(f"/api/v1/companies/{cid}", json={"active": False})
    assert patched.status_code == 200
    assert patched.json()["active"] is False

    listed = client.get("/api/v1/companies").json()
    assert any(c["id"] == cid for c in listed)

    assert client.delete(f"/api/v1/companies/{cid}").status_code == 204
    listed_after = client.get("/api/v1/companies").json()
    assert not any(c["id"] == cid for c in listed_after)


def test_create_company_duplicate_name(seeded_db):
    client, _ = seeded_db
    resp = client.post("/api/v1/companies", json={
        "name": "Stripe",
        "careers_url": "https://boards.greenhouse.io/stripe",
    })
    assert resp.status_code == 409


def test_bulk_import_csv(api_env):
    client, _ = api_env
    csv_text = (
        "name,careers_url,ats_type,ats_identifier\n"
        "Linear,https://jobs.ashbyhq.com/linear,ashby,linear\n"
        "Figma,https://jobs.lever.co/figma,lever,figma\n"
        ",missing-name,custom,\n"  # invalid row
    )
    resp = client.post(
        "/api/v1/companies/bulk-import",
        files={"file": ("companies.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["inserted"] == 2
    assert body["skipped"] == 1
    assert body["errors"]

    names = {c["name"] for c in client.get("/api/v1/companies").json()}
    assert {"Linear", "Figma"} <= names


def test_bulk_import_rejects_bad_csv(api_env):
    client, _ = api_env
    resp = client.post(
        "/api/v1/companies/bulk-import",
        files={"file": ("bad.csv", io.BytesIO(b"foo,bar\n1,2\n"), "text/csv")},
    )
    assert resp.status_code == 400


def test_stats(seeded_db):
    client, _ = seeded_db
    body = client.get("/api/v1/stats").json()
    assert body["companies_total"] == 3
    assert body["companies_active"] == 2
    assert body["jobs_total"] == 8        # all jobs in DB
    assert body["jobs_active"] == 7       # OldCo o1 is inactive
    assert body["jobs_last_15d"] >= 6     # active + recent
    assert body["last_run"] is not None
    assert body["last_run"]["status"] == "ok"


def test_scrape_runs_list(seeded_db):
    client, _ = seeded_db
    runs = client.get("/api/v1/scrape-runs").json()
    assert len(runs) == 2
    # Sorted desc by started_at — the latest run is first.
    assert runs[0]["started_at"] >= runs[1]["started_at"]


def test_scrape_runs_get_404(api_env):
    client, _ = api_env
    assert client.get("/api/v1/scrape-runs/9999").status_code == 404


def test_companies_health(seeded_db):
    client, _ = seeded_db
    health = client.get("/api/v1/stats/companies").json()
    by_name = {h["name"]: h for h in health}
    assert by_name["Stripe"]["jobs_active"] == 3
    assert by_name["Netflix"]["jobs_active"] == 3
    # OldCo has o1 (inactive) + o2 (active but old). jobs_active counts active=True only.
    assert by_name["OldCo"]["jobs_active"] == 1
    assert by_name["OldCo"]["active"] is False


def test_health_endpoint(api_env):
    client, _ = api_env
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["version"]


def test_api_key_required_when_configured(api_env, monkeypatch):
    """When JOBPULSE_API_KEY is set, mutating endpoints reject anonymous calls."""
    client, settings_ = api_env

    import dataclasses

    from backend import config
    import backend.api.deps as deps_mod

    new = dataclasses.replace(settings_, api_key="secret123")
    monkeypatch.setattr(config, "settings", new)
    monkeypatch.setattr(deps_mod, "settings", new)

    # No key → 401
    r = client.post("/api/v1/companies", json={
        "name": "Test", "careers_url": "https://example.com"
    })
    assert r.status_code == 401

    # With key → 201
    r = client.post(
        "/api/v1/companies",
        json={"name": "Test", "careers_url": "https://example.com"},
        headers={"X-API-Key": "secret123"},
    )
    assert r.status_code == 201
