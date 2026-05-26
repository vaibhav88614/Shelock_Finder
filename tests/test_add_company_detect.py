"""Tests for the URL-based ATS auto-detection wired into add-company + API."""
from __future__ import annotations

import io


def test_api_create_company_auto_detects_greenhouse(api_env):
    client, _ = api_env
    resp = client.post("/api/v1/companies", json={
        "name": "Stripe",
        "careers_url": "https://boards.greenhouse.io/stripe",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ats_type"] == "greenhouse"
    assert body["ats_identifier"] == "stripe"


def test_api_create_company_explicit_ats_overrides_detection(api_env):
    client, _ = api_env
    resp = client.post("/api/v1/companies", json={
        "name": "Forced",
        "careers_url": "https://boards.greenhouse.io/whatever",
        "ats_type": "custom",
    })
    assert resp.status_code == 201
    assert resp.json()["ats_type"] == "custom"


def test_api_create_company_unknown_url_falls_back_to_custom(api_env):
    client, _ = api_env
    resp = client.post("/api/v1/companies", json={
        "name": "Unknown",
        "careers_url": "https://random-startup.example.com/jobs",
    })
    assert resp.status_code == 201
    assert resp.json()["ats_type"] == "custom"
    assert resp.json()["ats_identifier"] is None


def test_api_bulk_import_auto_detects(api_env):
    client, _ = api_env
    csv_text = (
        "name,careers_url\n"
        "Netflix,https://jobs.lever.co/netflix\n"
        "Linear,https://jobs.ashbyhq.com/linear\n"
        "MysteryCo,https://mystery.example.com/jobs\n"
    )
    resp = client.post(
        "/api/v1/companies/bulk-import",
        files={"file": ("rows.csv", io.BytesIO(csv_text.encode()), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["inserted"] == 3

    listed = {c["name"]: c for c in client.get("/api/v1/companies").json()}
    assert listed["Netflix"]["ats_type"] == "lever"
    assert listed["Netflix"]["ats_identifier"] == "netflix"
    assert listed["Linear"]["ats_type"] == "ashby"
    assert listed["MysteryCo"]["ats_type"] == "custom"


def test_api_detect_endpoint_recognized(api_env):
    client, _ = api_env
    resp = client.get("/api/v1/companies/detect", params={"url": "https://boards.greenhouse.io/anthropic"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ats_type": "greenhouse", "ats_identifier": "anthropic", "recognized": True}


def test_api_detect_endpoint_unknown(api_env):
    client, _ = api_env
    resp = client.get("/api/v1/companies/detect", params={"url": "https://acme.example.com/careers"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ats_type": None, "ats_identifier": None, "recognized": False}


def test_api_detect_endpoint_requires_url(api_env):
    client, _ = api_env
    assert client.get("/api/v1/companies/detect").status_code == 422


def test_add_company_cli_helper_uses_detection(api_env):
    """`backend.add_company.add_company()` should populate ats_type + identifier."""
    from backend.add_company import add_company
    from backend.db import session_scope
    from backend.models import Company

    cid = add_company(url="https://boards.greenhouse.io/anthropic", name="Anthropic")
    with session_scope() as s:
        c = s.get(Company, cid)
        assert c is not None
        assert c.ats_type == "greenhouse"
        assert c.ats_identifier == "anthropic"
