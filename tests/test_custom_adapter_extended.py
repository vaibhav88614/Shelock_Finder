"""Extended `CustomAdapter` tests covering edge cases beyond the happy path.

The base `test_custom_adapter.py` exercises the happy path. This file adds:

  - Detail-page fetching (`detail_link` + `detail_description` selectors).
  - Malformed `custom_selectors` raises `AdapterError` cleanly (not a cryptic
    AttributeError or KeyError).
  - Relative URL absolutization for both `apply_url` and `detail_link`.
  - Missing required keys are rejected by `validate_selectors`.
  - Detail-fetch failures are non-fatal — the row keeps its index-page
    description and is still returned.
"""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from backend.adapters import CustomAdapter
from backend.adapters.base import AdapterError


INDEX_HTML = """
<!doctype html>
<html><body>
  <main>
    <article class="job">
      <h3 class="title">Backend Engineer</h3>
      <a class="apply" href="/jobs/be-001">Apply</a>
      <p class="excerpt">Index-page excerpt for BE.</p>
    </article>
    <article class="job">
      <h3 class="title">Frontend Engineer</h3>
      <a class="apply" href="//acme.example.com/jobs/fe-002">Apply</a>
    </article>
  </main>
</body></html>
"""

DETAIL_BE = """
<html><body>
  <div class="job-desc">
    <p>Full job description for the backend role.</p>
    <ul><li>Python</li><li>Postgres</li></ul>
  </div>
</body></html>
"""


def _make_company(fake_company, *, selectors):
    company = fake_company(
        ats_type="custom",
        ats_identifier=None,
        careers_url="https://acme.example.com/careers",
        name="Acme",
    )
    company.custom_selectors = json.dumps(selectors)
    return company


# --- Selector validation ----------------------------------------------------


@pytest.mark.parametrize(
    "spec",
    [
        {},  # all required keys missing
        {"list_item": "div"},  # missing title + apply_url
        {"list_item": "div", "title": "h3"},  # missing apply_url
        {"list_item": "", "title": "h3", "apply_url": "a@href"},  # empty list_item
        {"list_item": "div", "title": "   ", "apply_url": "a@href"},  # whitespace-only title
    ],
)
async def test_missing_or_blank_required_selector_raises(fake_company, spec):
    company = _make_company(fake_company, selectors=spec)
    adapter = CustomAdapter()
    with pytest.raises(AdapterError):
        await adapter.fetch(company)


async def test_non_json_selectors_raises(fake_company):
    company = fake_company(
        ats_type="custom",
        ats_identifier=None,
        careers_url="https://acme.example.com/careers",
        name="Acme",
    )
    company.custom_selectors = "not-actually-json {"
    adapter = CustomAdapter()
    with pytest.raises(AdapterError):
        await adapter.fetch(company)


async def test_missing_selectors_raises(fake_company):
    company = fake_company(
        ats_type="custom",
        ats_identifier=None,
        careers_url="https://acme.example.com/careers",
        name="Acme",
    )
    # No custom_selectors attribute at all.
    if hasattr(company, "custom_selectors"):
        delattr(company, "custom_selectors")
    adapter = CustomAdapter()
    with pytest.raises(AdapterError):
        await adapter.fetch(company)


# --- Relative URL absolutization -------------------------------------------


@respx.mock
async def test_relative_apply_url_is_absolutized(fake_company):
    spec = {
        "list_item": "article.job",
        "title": "h3.title",
        "apply_url": "a.apply@href",
    }
    company = _make_company(fake_company, selectors=spec)
    respx.get("https://acme.example.com/careers").mock(
        return_value=httpx.Response(200, text=INDEX_HTML)
    )

    adapter = CustomAdapter()
    raws = await adapter.fetch(company)
    # `/jobs/be-001` becomes absolute against the list URL; `//acme.example.com/jobs/fe-002`
    # also becomes absolute (the urljoin treats scheme-relative URLs correctly).
    urls = [r["apply_url"] for r in raws]
    assert urls[0] == "https://acme.example.com/jobs/be-001"
    assert urls[1] == "https://acme.example.com/jobs/fe-002"


# --- Detail page fetching ---------------------------------------------------


@respx.mock
async def test_detail_page_enriches_description(fake_company):
    spec = {
        "list_item": "article.job",
        "title": "h3.title",
        "apply_url": "a.apply@href",
        "description": "p.excerpt",
        "detail_link": "a.apply@href",
        "detail_description": "div.job-desc",
    }
    company = _make_company(fake_company, selectors=spec)

    respx.get("https://acme.example.com/careers").mock(
        return_value=httpx.Response(200, text=INDEX_HTML)
    )
    respx.get("https://acme.example.com/jobs/be-001").mock(
        return_value=httpx.Response(200, text=DETAIL_BE)
    )
    # Second row's detail page returns a 404 so we also exercise the
    # graceful-degradation path. Its description should remain whatever the
    # index page provided (None for this row).
    respx.get("https://acme.example.com/jobs/fe-002").mock(
        return_value=httpx.Response(404, text="")
    )

    adapter = CustomAdapter()
    raws = await adapter.fetch(company)
    descs = [r.get("description") for r in raws]
    # Row 1: description overridden from detail page.
    assert descs[0] is not None
    assert "Full job description" in descs[0]
    # Row 2: detail fetch 404'd → description stays None (no index excerpt).
    assert descs[1] is None


# --- Custom list_url overrides careers_url ---------------------------------


@respx.mock
async def test_list_url_in_spec_overrides_careers_url(fake_company):
    spec = {
        "list_item": "article.job",
        "title": "h3.title",
        "apply_url": "a.apply@href",
        "list_url": "https://different.example.com/jobs",
    }
    company = _make_company(fake_company, selectors=spec)

    # The `careers_url` (acme) must NOT be hit; the spec's `list_url` is used.
    respx.get("https://different.example.com/jobs").mock(
        return_value=httpx.Response(200, text=INDEX_HTML)
    )

    adapter = CustomAdapter()
    raws = await adapter.fetch(company)
    assert len(raws) == 2
    # Relative URLs now resolve against the spec list_url, not careers_url.
    assert raws[0]["apply_url"].startswith("https://different.example.com/")
