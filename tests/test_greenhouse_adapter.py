"""Tests for `GreenhouseAdapter`.

Uses `respx` to mock the public Greenhouse JSON endpoint with a recorded
fixture so the suite runs offline.
"""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from backend.adapters import GreenhouseAdapter, get_adapter_cls
from backend.adapters.base import AdapterError


def test_registry_returns_greenhouse():
    assert get_adapter_cls("greenhouse") is GreenhouseAdapter


@respx.mock
async def test_fetch_and_normalize_happy_path(load_fixture, fake_company):
    payload = load_fixture("greenhouse_teststripe.json")
    respx.get("https://boards-api.greenhouse.io/v1/boards/teststripe/jobs?content=true").mock(
        return_value=httpx.Response(200, json=payload)
    )

    company = fake_company(ats_type="greenhouse", ats_identifier="teststripe", name="TestStripe")
    adapter = GreenhouseAdapter()
    try:
        raws = await adapter.fetch(company)
        assert len(raws) == 3

        jobs = [adapter.normalize(r, company) for r in raws]

        # Job 1: range 5-8 years, SF
        j1 = jobs[0]
        assert j1.external_id == "4567890"
        assert j1.title == "Senior Software Engineer, Payments"
        assert j1.apply_url.startswith("https://boards.greenhouse.io/teststripe/jobs/")
        assert j1.location == "San Francisco, CA"
        assert j1.department == "Engineering"
        assert j1.employment_type == "Full Time"
        assert j1.experience_min == 5 and j1.experience_max == 8
        assert j1.remote_type is None
        assert j1.description and "<" not in j1.description, "HTML stripped"
        assert j1.posted_date is not None and j1.posted_date.year == 2026

        # Job 2: minimum 7 years, remote
        j2 = jobs[1]
        assert j2.experience_min == 7 and j2.experience_max is None
        assert j2.remote_type == "remote"

        # Job 3: no experience signal, hybrid via location hint
        j3 = jobs[2]
        assert j3.experience_min is None and j3.experience_max is None
        assert j3.remote_type == "hybrid"
    finally:
        await adapter.aclose()


@respx.mock
async def test_fetch_raises_on_404(fake_company):
    respx.get("https://boards-api.greenhouse.io/v1/boards/missingco/jobs?content=true").mock(
        return_value=httpx.Response(404, text="not found")
    )
    adapter = GreenhouseAdapter()
    try:
        with pytest.raises(AdapterError, match="not found"):
            await adapter.fetch(fake_company(ats_identifier="missingco"))
    finally:
        await adapter.aclose()


@respx.mock
async def test_fetch_raises_on_non_json(fake_company):
    respx.get("https://boards-api.greenhouse.io/v1/boards/oops/jobs?content=true").mock(
        return_value=httpx.Response(200, text="<html>not json</html>")
    )
    adapter = GreenhouseAdapter()
    try:
        with pytest.raises(AdapterError, match="non-JSON"):
            await adapter.fetch(fake_company(ats_identifier="oops"))
    finally:
        await adapter.aclose()


async def test_fetch_raises_without_identifier(fake_company):
    adapter = GreenhouseAdapter()
    try:
        with pytest.raises(AdapterError, match="ats_identifier"):
            await adapter.fetch(fake_company(ats_identifier=""))
    finally:
        await adapter.aclose()


def test_fingerprint_is_stable_across_calls(load_fixture, fake_company):
    payload = load_fixture("greenhouse_teststripe.json")
    company = fake_company(id=42, ats_type="greenhouse", ats_identifier="teststripe")
    adapter = GreenhouseAdapter()
    j = adapter.normalize(payload["jobs"][0], company)
    fp1 = adapter.fingerprint_for(company.id, j)
    fp2 = adapter.fingerprint_for(company.id, j)
    assert fp1 == fp2
    assert len(fp1) == 64
