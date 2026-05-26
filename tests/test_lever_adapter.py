"""Tests for `LeverAdapter`."""
from __future__ import annotations

import httpx
import pytest
import respx

from backend.adapters import LeverAdapter, get_adapter_cls
from backend.adapters.base import AdapterError


def test_registry_returns_lever():
    assert get_adapter_cls("lever") is LeverAdapter


@respx.mock
async def test_fetch_and_normalize_happy_path(load_fixture, fake_company):
    payload = load_fixture("lever_testnetflix.json")
    respx.get("https://api.lever.co/v0/postings/testnetflix?mode=json").mock(
        return_value=httpx.Response(200, json=payload)
    )

    company = fake_company(ats_type="lever", ats_identifier="testnetflix", name="TestNetflix")
    adapter = LeverAdapter()
    try:
        raws = await adapter.fetch(company)
        assert len(raws) == 2

        jobs = [adapter.normalize(r, company) for r in raws]

        # Job 1: 6+ years, hybrid, Los Gatos
        j1 = jobs[0]
        assert j1.external_id == "8a7b6c5d-1111-2222-3333-444455556666"
        assert j1.title == "Senior Backend Engineer, Platform"
        assert j1.apply_url.startswith("https://jobs.lever.co/testnetflix/")
        assert j1.location == "Los Gatos, CA"
        assert j1.department == "Platform Engineering"
        assert j1.employment_type == "Full-time"
        assert j1.experience_min == 6 and j1.experience_max is None
        assert j1.remote_type == "hybrid"
        assert j1.posted_date is not None and j1.posted_date.year == 2026
        # Description should include additionalPlain merged in for keyword/exp parsing.
        assert "c++" in (j1.description or "").lower()

        # Job 2: 3-5 years, remote
        j2 = jobs[1]
        assert j2.experience_min == 3 and j2.experience_max == 5
        assert j2.remote_type == "remote"
        assert j2.department == "Data Science"
    finally:
        await adapter.aclose()


@respx.mock
async def test_fetch_raises_on_non_array(fake_company):
    respx.get("https://api.lever.co/v0/postings/oops?mode=json").mock(
        return_value=httpx.Response(200, json={"oops": True})
    )
    adapter = LeverAdapter()
    try:
        with pytest.raises(AdapterError, match="JSON array"):
            await adapter.fetch(fake_company(ats_type="lever", ats_identifier="oops"))
    finally:
        await adapter.aclose()


@respx.mock
async def test_fetch_raises_on_404(fake_company):
    respx.get("https://api.lever.co/v0/postings/missingco?mode=json").mock(
        return_value=httpx.Response(404)
    )
    adapter = LeverAdapter()
    try:
        with pytest.raises(AdapterError, match="not found"):
            await adapter.fetch(fake_company(ats_type="lever", ats_identifier="missingco"))
    finally:
        await adapter.aclose()
