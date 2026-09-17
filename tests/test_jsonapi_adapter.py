"""Tests for `JsonApiAdapter` (generic JSON-API adapter)."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import respx

from backend.adapters import JsonApiAdapter, get_adapter_cls
from backend.adapters.base import AdapterError


def _co(cfg: dict, name: str = "Test Co") -> SimpleNamespace:
    return SimpleNamespace(
        id=1, name=name, ats_type="jsonapi", ats_identifier=None,
        careers_url="", custom_selectors=cfg,
    )


def test_registry_returns_jsonapi():
    assert get_adapter_cls("jsonapi") is JsonApiAdapter


@respx.mock
async def test_flat_array_with_url_base():
    cfg = {
        "api_url": "https://api.example.com/search.json",
        "jobs_path": "jobs",
        "url_base": "https://api.example.com",
        "fields": {
            "external_id": "id", "title": "title", "apply_url": "path",
            "location": "loc", "posted_date": "posted", "department": "dept",
        },
    }
    payload = {"jobs": [
        {"id": "1", "title": "Engineer", "path": "/jobs/1/eng", "loc": "NYC, USA",
         "posted": "September 16, 2026", "dept": "Eng"},
        {"id": "2", "title": ["Data", "Scientist"], "path": "https://x.co/2", "loc": "Remote"},
    ]}
    respx.route(method="GET", url__startswith="https://api.example.com/search.json").mock(
        return_value=httpx.Response(200, json=payload)
    )
    a = JsonApiAdapter()
    try:
        raws = await a.fetch(_co(cfg))
        assert len(raws) == 2
        jobs = [a.normalize(r, _co(cfg)) for r in raws]
        assert jobs[0].title == "Engineer"
        assert jobs[0].apply_url == "https://api.example.com/jobs/1/eng"  # relative -> absolute
        assert jobs[0].location == "NYC, USA"
        assert jobs[0].external_id == "1"
        assert jobs[0].posted_date is not None and jobs[0].posted_date.year == 2026
        assert jobs[1].title == "Data, Scientist"  # list coerced by as_text
        assert jobs[1].apply_url == "https://x.co/2"  # already absolute, unchanged
    finally:
        await a.aclose()


@respx.mock
async def test_nested_jobs_path_and_url_template():
    cfg = {
        "api_url": "https://oracle.example.com/rest/jobs",
        "jobs_path": "items.0.requisitionList",
        "url_template": "https://oracle.example.com/site/job/{Id}",
        "fields": {"external_id": "Id", "title": "Title", "location": "PrimaryLocation"},
    }
    payload = {"items": [{"requisitionList": [
        {"Id": "R1", "Title": "Analyst", "PrimaryLocation": "Bengaluru, India"},
    ]}]}
    respx.route(method="GET", url__startswith="https://oracle.example.com/rest/jobs").mock(
        return_value=httpx.Response(200, json=payload)
    )
    a = JsonApiAdapter()
    try:
        raws = await a.fetch(_co(cfg))
        assert len(raws) == 1
        nj = a.normalize(raws[0], _co(cfg))
        assert nj.title == "Analyst"
        assert nj.apply_url == "https://oracle.example.com/site/job/R1"
        assert nj.location == "Bengaluru, India"
    finally:
        await a.aclose()


@respx.mock
async def test_top_level_array_jobs_path():
    cfg = {
        "api_url": "https://api.example.com/all",
        "jobs_path": "$",
        "url_template": "https://x.co/j/{id}",
        "fields": {"external_id": "id", "title": "title", "location": "loc"},
    }
    payload = [
        {"id": "1", "title": "A", "loc": "NYC"},
        {"id": "2", "title": "B", "loc": "LA"},
    ]
    respx.route(method="GET", url__startswith="https://api.example.com/all").mock(
        return_value=httpx.Response(200, json=payload)
    )
    a = JsonApiAdapter()
    try:
        raws = await a.fetch(_co(cfg))
        assert len(raws) == 2
        nj = a.normalize(raws[0], _co(cfg))
        assert nj.title == "A" and nj.apply_url == "https://x.co/j/1"
    finally:
        await a.aclose()


@respx.mock
async def test_pagination_stops_on_short_page():
    cfg = {
        "api_url": "https://api.example.com/j",
        "jobs_path": "jobs", "page_param": "offset", "page_size": 2, "max_records": 100,
        "url_base": "https://api.example.com",
        "fields": {"title": "t", "apply_url": "u"},
    }

    def responder(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))
        if offset == 0:
            return httpx.Response(200, json={"jobs": [{"t": "a", "u": "/1"}, {"t": "b", "u": "/2"}]})
        return httpx.Response(200, json={"jobs": [{"t": "c", "u": "/3"}]})  # short -> stop

    respx.route(method="GET", url__startswith="https://api.example.com/j").mock(side_effect=responder)
    a = JsonApiAdapter()
    try:
        raws = await a.fetch(_co(cfg))
        assert len(raws) == 3
    finally:
        await a.aclose()


async def test_missing_config_raises():
    a = JsonApiAdapter()
    try:
        with pytest.raises(AdapterError):
            await a.fetch(_co({"jobs_path": "jobs"}))  # no api_url
        with pytest.raises(AdapterError):
            await a.fetch(_co({"api_url": "x", "fields": {}}))  # no fields.title
    finally:
        await a.aclose()
