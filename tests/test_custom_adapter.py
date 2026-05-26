"""Tests for `CustomAdapter` (BeautifulSoup tier-2 HTML adapter)."""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from backend.adapters import CustomAdapter, get_adapter_cls
from backend.adapters.base import AdapterError


INDEX_HTML = """
<!doctype html>
<html><body>
  <main>
    <article class="job">
      <h2><a class="title" href="/careers/eng-001">Senior Backend Engineer</a></h2>
      <span class="loc">Remote - EU</span>
      <span class="dept">Engineering</span>
      <span class="type">Full-time</span>
      <time class="posted" datetime="2026-05-12">May 12, 2026</time>
      <p class="excerpt">Build scalable APIs with 5+ years experience.</p>
    </article>
    <article class="job">
      <h2><a class="title" href="https://acme.example.com/careers/design-002">Senior Product Designer</a></h2>
      <span class="loc">Berlin</span>
      <span class="dept">Design</span>
      <span class="type">Full-time</span>
      <time class="posted" datetime="2026-05-18">May 18, 2026</time>
      <p class="excerpt">3-5 years experience.</p>
    </article>
    <article class="job">
      <h2><a class="title">Missing href won't be returned</a></h2>
    </article>
  </main>
</body></html>
"""

DETAIL_HTML_1 = """
<html><body><div class="job-body">
  <h1>Senior Backend Engineer</h1>
  <p>We need someone with 5+ years of Python and Postgres experience.</p>
  <p>Remote-friendly EU role.</p>
</div></body></html>
"""

SELECTORS = {
    "list_item": "article.job",
    "title": "a.title",
    "apply_url": "a.title@href",
    "location": "span.loc",
    "department": "span.dept",
    "employment_type": "span.type",
    "posted_date": "time.posted@datetime",
    "description": "p.excerpt",
}


def _make_company(fake_company, *, selectors=SELECTORS, detail=False):
    spec = dict(selectors)
    if detail:
        spec["detail_link"] = "a.title@href"
        spec["detail_description"] = "div.job-body"
    return fake_company(
        ats_type="custom",
        ats_identifier=None,
        careers_url="https://acme.example.com/careers",
        name="Acme",
    ), spec


def test_registry_returns_custom():
    assert get_adapter_cls("custom") is CustomAdapter


@respx.mock
async def test_fetch_and_normalize_happy(fake_company):
    company, spec = _make_company(fake_company)
    company.custom_selectors = json.dumps(spec)

    respx.get("https://acme.example.com/careers").mock(
        return_value=httpx.Response(200, text=INDEX_HTML, headers={"content-type": "text/html"})
    )

    adapter = CustomAdapter()
    try:
        raws = await adapter.fetch(company)
        # Third article had no href and must be dropped.
        assert len(raws) == 2

        jobs = [adapter.normalize(r, company) for r in raws]

        j1 = jobs[0]
        assert j1.title == "Senior Backend Engineer"
        # Relative href must be absolutised against the list URL.
        assert j1.apply_url == "https://acme.example.com/careers/eng-001"
        assert j1.location == "Remote - EU"
        assert j1.department == "Engineering"
        assert j1.employment_type == "Full-time"
        assert j1.remote_type == "remote"
        assert j1.experience_min == 5 and j1.experience_max is None
        assert j1.posted_date is not None and j1.posted_date.year == 2026
        assert j1.external_id is None  # fingerprint uses fallback

        j2 = jobs[1]
        # Absolute href preserved.
        assert j2.apply_url == "https://acme.example.com/careers/design-002"
        assert j2.experience_min == 3 and j2.experience_max == 5
    finally:
        await adapter.aclose()


@respx.mock
async def test_fetch_with_detail_pages(fake_company):
    company, spec = _make_company(fake_company, detail=True)
    company.custom_selectors = json.dumps(spec)

    respx.get("https://acme.example.com/careers").mock(
        return_value=httpx.Response(200, text=INDEX_HTML)
    )
    respx.get("https://acme.example.com/careers/eng-001").mock(
        return_value=httpx.Response(200, text=DETAIL_HTML_1)
    )
    respx.get("https://acme.example.com/careers/design-002").mock(
        return_value=httpx.Response(200, text="<html><body><div class='job-body'>Design role 4 years.</div></body></html>")
    )

    adapter = CustomAdapter()
    try:
        raws = await adapter.fetch(company)
        jobs = [adapter.normalize(r, company) for r in raws]
        assert "5+ years of Python" in (jobs[0].description or "")
        assert "Design role" in (jobs[1].description or "")
    finally:
        await adapter.aclose()


@respx.mock
async def test_fetch_uses_list_url_override(fake_company):
    company, spec = _make_company(fake_company)
    spec["list_url"] = "https://acme.example.com/other-careers"
    company.custom_selectors = json.dumps(spec)

    respx.get("https://acme.example.com/other-careers").mock(
        return_value=httpx.Response(200, text=INDEX_HTML)
    )

    adapter = CustomAdapter()
    try:
        raws = await adapter.fetch(company)
        assert len(raws) == 2
    finally:
        await adapter.aclose()


async def test_custom_requires_selectors(fake_company):
    c = fake_company(ats_type="custom", ats_identifier=None,
                     careers_url="https://x/")
    c.custom_selectors = None
    adapter = CustomAdapter()
    try:
        with pytest.raises(AdapterError, match="custom_selectors"):
            await adapter.fetch(c)
    finally:
        await adapter.aclose()


async def test_custom_validates_required_keys(fake_company):
    c = fake_company(ats_type="custom", ats_identifier=None,
                     careers_url="https://x/")
    c.custom_selectors = json.dumps({"list_item": ".row"})  # missing title + apply_url
    adapter = CustomAdapter()
    try:
        with pytest.raises(AdapterError, match="missing required"):
            await adapter.fetch(c)
    finally:
        await adapter.aclose()


@respx.mock
async def test_custom_500_raises_adapter_error(fake_company):
    company, spec = _make_company(fake_company)
    company.custom_selectors = json.dumps(spec)
    respx.get("https://acme.example.com/careers").mock(
        return_value=httpx.Response(503, text="busy")
    )
    adapter = CustomAdapter()
    try:
        with pytest.raises(AdapterError, match="HTTP 503"):
            await adapter.fetch(company)
    finally:
        await adapter.aclose()


# ---- Playwright registry only (real browser tests skipped) -----------------


def test_playwright_registered():
    """Without playwright installed, the registry still exposes the class."""
    from backend.adapters import PlaywrightAdapter
    assert get_adapter_cls("playwright") is PlaywrightAdapter
    assert PlaywrightAdapter.ats_type == "playwright"
