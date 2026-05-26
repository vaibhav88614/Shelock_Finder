"""Smoke tests for phase-5 ATS adapters.

Each adapter gets:
  * a registry-lookup assertion
  * a `fetch + normalize` happy-path test against a recorded fixture mocked via respx
  * an `AdapterError` test for a 404 / bad-shape response
"""
from __future__ import annotations

import httpx
import pytest
import respx

from backend.adapters import (
    ADAPTERS,
    AshbyAdapter,
    PersonioAdapter,
    RecruiteeAdapter,
    SmartRecruitersAdapter,
    TeamtailorAdapter,
    WorkableAdapter,
    WorkdayAdapter,
    get_adapter_cls,
)
from backend.adapters.base import AdapterError


# --- registry ----------------------------------------------------------------


def test_registry_contains_all_phase5_adapters():
    for name in (
        "greenhouse", "lever", "workday", "smartrecruiters",
        "ashby", "workable", "recruitee", "personio", "teamtailor",
    ):
        assert name in ADAPTERS
        assert get_adapter_cls(name) is ADAPTERS[name]


# --- SmartRecruiters ---------------------------------------------------------


@respx.mock
async def test_smartrecruiters_happy(load_fixture, fake_company):
    payload = load_fixture("smartrecruiters_testbox.json")
    respx.get(
        "https://api.smartrecruiters.com/v1/companies/TestBox/postings?limit=100&offset=0"
    ).mock(return_value=httpx.Response(200, json=payload))

    company = fake_company(ats_type="smartrecruiters", ats_identifier="TestBox", name="TestBox")
    adapter = SmartRecruitersAdapter()
    try:
        raws = await adapter.fetch(company)
        assert len(raws) == 2
        jobs = [adapter.normalize(r, company) for r in raws]

        j1 = jobs[0]
        assert j1.external_id == "743999111111"
        assert j1.title == "Senior Software Engineer, Backend"
        assert j1.apply_url.startswith("https://jobs.smartrecruiters.com/TestBox/")
        assert j1.location == "Redwood City, CA, us"
        assert j1.department == "Engineering"
        assert j1.employment_type == "Full-time"
        assert j1.experience_min == 5 and j1.experience_max == 8
        assert j1.posted_date is not None and j1.posted_date.year == 2026
        assert j1.remote_type is None

        j2 = jobs[1]
        assert j2.remote_type == "remote"
        assert j2.experience_min == 7 and j2.experience_max is None
    finally:
        await adapter.aclose()


@respx.mock
async def test_smartrecruiters_404(fake_company):
    respx.get(
        "https://api.smartrecruiters.com/v1/companies/missing/postings?limit=100&offset=0"
    ).mock(return_value=httpx.Response(404, text="not found"))
    adapter = SmartRecruitersAdapter()
    try:
        with pytest.raises(AdapterError, match="not found"):
            await adapter.fetch(fake_company(ats_type="smartrecruiters", ats_identifier="missing"))
    finally:
        await adapter.aclose()


# --- Ashby -------------------------------------------------------------------


@respx.mock
async def test_ashby_happy(load_fixture, fake_company):
    payload = load_fixture("ashby_testlinear.json")
    respx.get(
        "https://api.ashbyhq.com/posting-api/job-board/testlinear?includeCompensation=false"
    ).mock(return_value=httpx.Response(200, json=payload))

    company = fake_company(ats_type="ashby", ats_identifier="testlinear", name="TestLinear")
    adapter = AshbyAdapter()
    try:
        raws = await adapter.fetch(company)
        # The unlisted draft must be filtered out.
        assert len(raws) == 2

        jobs = [adapter.normalize(r, company) for r in raws]

        j1 = jobs[0]
        assert j1.title == "Senior Frontend Engineer"
        assert j1.location == "San Francisco, CA"
        assert j1.employment_type == "Full-time"
        assert j1.department == "Engineering"
        assert j1.experience_min == 4 and j1.experience_max == 7
        assert j1.posted_date is not None and j1.posted_date.year == 2026

        j2 = jobs[1]
        assert j2.remote_type == "remote"
        assert j2.title == "Junior Designer"
    finally:
        await adapter.aclose()


@respx.mock
async def test_ashby_bad_shape(fake_company):
    respx.get(
        "https://api.ashbyhq.com/posting-api/job-board/oops?includeCompensation=false"
    ).mock(return_value=httpx.Response(200, json={"oops": True}))
    adapter = AshbyAdapter()
    try:
        with pytest.raises(AdapterError, match="missing 'jobs'"):
            await adapter.fetch(fake_company(ats_type="ashby", ats_identifier="oops"))
    finally:
        await adapter.aclose()


# --- Workable ----------------------------------------------------------------


@respx.mock
async def test_workable_happy(load_fixture, fake_company):
    payload = load_fixture("workable_testlyft.json")
    respx.post(
        "https://apply.workable.com/api/v3/accounts/testlyft/jobs"
    ).mock(return_value=httpx.Response(200, json=payload))

    company = fake_company(ats_type="workable", ats_identifier="testlyft", name="TestLyft")
    adapter = WorkableAdapter()
    try:
        raws = await adapter.fetch(company)
        assert len(raws) == 2
        jobs = [adapter.normalize(r, company) for r in raws]

        j1 = jobs[0]
        assert j1.external_id == "ABC123"
        assert j1.title == "Senior Data Engineer"
        assert j1.location == "Berlin, Germany"
        assert j1.department == "Data"
        assert j1.experience_min == 5 and j1.experience_max == 8
        assert j1.posted_date is not None and j1.posted_date.year == 2026

        j2 = jobs[1]
        assert j2.remote_type == "remote"
        assert j2.experience_min == 3 and j2.experience_max == 5
    finally:
        await adapter.aclose()


@respx.mock
async def test_workable_404(fake_company):
    respx.post(
        "https://apply.workable.com/api/v3/accounts/missing/jobs"
    ).mock(return_value=httpx.Response(404))
    adapter = WorkableAdapter()
    try:
        with pytest.raises(AdapterError, match="not found"):
            await adapter.fetch(fake_company(ats_type="workable", ats_identifier="missing"))
    finally:
        await adapter.aclose()


# --- Recruitee ---------------------------------------------------------------


@respx.mock
async def test_recruitee_happy(load_fixture, fake_company):
    payload = load_fixture("recruitee_testrecruitee.json")
    respx.get(
        "https://testrecruitee.recruitee.com/api/offers/"
    ).mock(return_value=httpx.Response(200, json=payload))

    company = fake_company(
        ats_type="recruitee", ats_identifier="testrecruitee", name="TestRecruitee"
    )
    adapter = RecruiteeAdapter()
    try:
        raws = await adapter.fetch(company)
        assert len(raws) == 2
        jobs = [adapter.normalize(r, company) for r in raws]

        j1 = jobs[0]
        assert j1.external_id == "5551"
        assert j1.title == "Senior Product Manager"
        assert j1.location == "Amsterdam, Netherlands"
        assert j1.department == "Product"
        assert j1.experience_min == 6 and j1.experience_max is None
        assert j1.posted_date is not None and j1.posted_date.year == 2026

        j2 = jobs[1]
        assert j2.remote_type == "remote"
        assert j2.experience_min == 2 and j2.experience_max == 4
    finally:
        await adapter.aclose()


# --- Personio ----------------------------------------------------------------


@respx.mock
async def test_personio_happy(load_fixture, fake_company):
    xml_text = load_fixture("personio_testpersonio.xml")
    respx.get(
        "https://testpersonio.jobs.personio.de/xml"
    ).mock(return_value=httpx.Response(200, text=xml_text,
                                       headers={"content-type": "application/xml"}))

    company = fake_company(
        ats_type="personio", ats_identifier="testpersonio", name="TestPersonio"
    )
    adapter = PersonioAdapter()
    try:
        raws = await adapter.fetch(company)
        assert len(raws) == 2
        jobs = [adapter.normalize(r, company) for r in raws]

        j1 = jobs[0]
        assert j1.external_id == "1001"
        assert j1.title == "Senior Backend Engineer (m/f/d)"
        assert j1.location == "Munich"
        assert j1.department == "Engineering"
        assert j1.experience_min == 5 and j1.experience_max == 8
        assert j1.description and "python" in j1.description.lower()
        assert j1.posted_date is not None and j1.posted_date.year == 2026

        j2 = jobs[1]
        assert j2.location == "Remote"
        assert j2.remote_type == "remote"
        assert j2.experience_min == 2 and j2.experience_max == 4
    finally:
        await adapter.aclose()


@respx.mock
async def test_personio_invalid_xml(fake_company):
    respx.get(
        "https://oops.jobs.personio.de/xml"
    ).mock(return_value=httpx.Response(200, text="<not closed"))
    adapter = PersonioAdapter()
    try:
        with pytest.raises(AdapterError, match="invalid XML"):
            await adapter.fetch(fake_company(ats_type="personio", ats_identifier="oops"))
    finally:
        await adapter.aclose()


# --- Teamtailor --------------------------------------------------------------


@respx.mock
async def test_teamtailor_happy(load_fixture, fake_company):
    payload = load_fixture("teamtailor_testtt.json")
    respx.get(
        "https://testtt.teamtailor.com/jobs.json"
    ).mock(return_value=httpx.Response(200, json=payload))

    company = fake_company(ats_type="teamtailor", ats_identifier="testtt", name="TestTT")
    adapter = TeamtailorAdapter()
    try:
        raws = await adapter.fetch(company)
        assert len(raws) == 2
        jobs = [adapter.normalize(r, company) for r in raws]

        j1 = jobs[0]
        assert j1.external_id == "tt-1"
        assert j1.title == "Senior Marketing Manager"
        assert j1.location == "Stockholm, Sweden"
        assert j1.remote_type == "onsite"
        assert j1.experience_min == 5 and j1.experience_max == 8

        j2 = jobs[1]
        assert j2.remote_type == "remote"
    finally:
        await adapter.aclose()


@respx.mock
async def test_teamtailor_list_root(fake_company):
    """Teamtailor sometimes returns a top-level array; adapter should accept it."""
    respx.get(
        "https://altform.teamtailor.com/jobs.json"
    ).mock(return_value=httpx.Response(200, json=[{
        "id": "x", "title": "X", "careersite_job_url": "https://x/y",
        "published_at": "2026-05-01T00:00:00Z"
    }]))
    adapter = TeamtailorAdapter()
    try:
        raws = await adapter.fetch(
            fake_company(ats_type="teamtailor", ats_identifier="altform")
        )
        assert len(raws) == 1
        assert adapter.normalize(raws[0], fake_company()).title == "X"
    finally:
        await adapter.aclose()


# --- Workday -----------------------------------------------------------------


@respx.mock
async def test_workday_happy(load_fixture, fake_company):
    payload = load_fixture("workday_testnvidia.json")
    host = "testnvidia.wd5.myworkdayjobs.com"
    respx.post(
        f"https://{host}/wday/cxs/nvidia/Careers/jobs"
    ).mock(return_value=httpx.Response(200, json=payload))

    company = fake_company(
        ats_type="workday",
        ats_identifier=f"{host}|nvidia|Careers",
        name="TestNvidia",
    )
    adapter = WorkdayAdapter()
    try:
        raws = await adapter.fetch(company)
        assert len(raws) == 2
        jobs = [adapter.normalize(r, company) for r in raws]

        j1 = jobs[0]
        assert j1.external_id == "JR-100001"
        assert j1.title == "Senior Software Engineer, Compute"
        assert j1.apply_url == (
            f"https://{host}/job/Santa-Clara/Senior-Software-Engineer-Compute_JR-100001"
        )
        assert j1.location == "Santa Clara, CA, United States"
        # startDate wins over relative postedOn
        assert j1.posted_date is not None and j1.posted_date.year == 2026

        j2 = jobs[1]
        assert j2.external_id == "JR-100002"
        assert j2.remote_type == "remote"
        # falls back to relative-date parsing ("Posted Yesterday")
        assert j2.posted_date is not None
    finally:
        await adapter.aclose()


def test_workday_identifier_validation(fake_company):
    adapter = WorkdayAdapter()
    with pytest.raises(AdapterError, match="ats_identifier"):
        # Synchronous validation in fetch — but fetch is async. Trigger via parse helper directly.
        from backend.adapters.workday import _parse_workday_identifier
        _parse_workday_identifier("only|two")
