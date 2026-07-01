"""X-API-Key auth gate on mutating endpoints.

Covers the `require_api_key` dependency wired onto POST/PATCH/DELETE routes.
Default `api_env` fixture has `api_key=None` (no gate); this file adds a
counterpart fixture that sets `api_key="test-secret"` and verifies:

  - Missing header → 401 on every mutating endpoint.
  - Wrong header → 401.
  - Correct header → 200/202.
  - GET endpoints stay open in both modes (read-only local UX).
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest


def _no_op(*args, **kwargs):
    return 0


@pytest.fixture
def api_env_with_key(tmp_path, monkeypatch):
    """Spin up a TestClient with `JOBPULSE_API_KEY='test-secret'` configured."""
    from fastapi.testclient import TestClient

    from backend import config, db, migrations
    import backend.api.deps as deps_mod
    import backend.scrape as scrape_mod
    import backend.seed as seed_mod
    import backend.serve as serve_mod

    db_path: Path = tmp_path / "auth_jobpulse.db"
    data_dir: Path = tmp_path / "data"
    data_dir.mkdir()

    new_settings = dataclasses.replace(
        config.settings,
        db_path=db_path,
        data_dir=data_dir,
        api_key="test-secret",
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


# --- POST /companies ---------------------------------------------------------


def test_post_companies_no_header_401(api_env_with_key):
    client, _ = api_env_with_key
    r = client.post(
        "/api/v1/companies",
        json={"name": "Acme", "careers_url": "https://boards.greenhouse.io/acme"},
    )
    assert r.status_code == 401


def test_post_companies_wrong_header_401(api_env_with_key):
    client, _ = api_env_with_key
    r = client.post(
        "/api/v1/companies",
        json={"name": "Acme", "careers_url": "https://boards.greenhouse.io/acme"},
        headers={"X-API-Key": "wrong-key"},
    )
    assert r.status_code == 401


def test_post_companies_correct_header_succeeds(api_env_with_key):
    client, _ = api_env_with_key
    r = client.post(
        "/api/v1/companies",
        json={"name": "Acme", "careers_url": "https://boards.greenhouse.io/acme"},
        headers={"X-API-Key": "test-secret"},
    )
    # 200 (created) or 201 depending on the schema — either passes the gate.
    assert r.status_code in (200, 201)


# --- POST /scrape-runs -------------------------------------------------------


def test_post_scrape_runs_no_header_401(api_env_with_key, monkeypatch):
    client, _ = api_env_with_key
    monkeypatch.setattr("backend.scrape.run_scrape", _no_op)
    r = client.post("/api/v1/scrape-runs")
    assert r.status_code == 401


def test_post_scrape_runs_correct_header_202(api_env_with_key, monkeypatch):
    client, _ = api_env_with_key
    monkeypatch.setattr("backend.scrape.run_scrape", _no_op)
    r = client.post(
        "/api/v1/scrape-runs",
        headers={"X-API-Key": "test-secret"},
    )
    assert r.status_code == 202


# --- GET endpoints stay open -------------------------------------------------


def test_get_endpoints_open_without_key(api_env_with_key):
    """Read endpoints are unauthenticated by design (local single-user UX)."""
    client, _ = api_env_with_key
    assert client.get("/api/v1/stats").status_code == 200
    assert client.get("/api/v1/companies").status_code == 200
    assert client.get("/api/v1/jobs").status_code == 200
    assert client.get("/api/v1/scrape-runs").status_code == 200
    assert client.get("/health").status_code == 200


# --- Default api_env (no key configured) -------------------------------------


def test_no_key_configured_means_no_gate(api_env, monkeypatch):
    """When `JOBPULSE_API_KEY` is unset, mutating endpoints accept no header."""
    client, _ = api_env
    monkeypatch.setattr("backend.scrape.run_scrape", _no_op)
    r = client.post("/api/v1/scrape-runs")
    assert r.status_code == 202
    r = client.post(
        "/api/v1/companies",
        json={"name": "Acme2", "careers_url": "https://boards.greenhouse.io/acme2"},
    )
    assert r.status_code in (200, 201)
