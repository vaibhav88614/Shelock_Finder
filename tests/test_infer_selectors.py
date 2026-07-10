"""Tests for scripts/infer_selectors.py.

Covers the pure heuristics (job-title / job-link classification), the
`infer_selectors` brute-force engine on synthetic HTML (must produce a spec the
real `extract_rows` engine can use, and must decline nav-only pages), and the
`run_infer` orchestration (httpx-mocked; verifies seed updates + review CSV).
"""
from __future__ import annotations

import json

import httpx
import pytest
import respx

import scripts.infer_selectors as mod
from backend.adapters._html_extract import extract_rows, validate_selectors
from scripts.infer_selectors import (
    infer_selectors,
    looks_like_job_link,
    looks_like_job_title,
    run_infer,
)


JOB_HTML = """
<html><body>
<header><nav>
  <a href="/">Home</a><a href="/about">About Us</a><a href="/contact">Contact</a>
</nav></header>
<section class="careers">
  <ul class="job-list">
    <li class="job-item"><a href="/careers/senior-python-engineer"><h3>Senior Python Engineer</h3></a><span class="location">Bengaluru</span></li>
    <li class="job-item"><a href="/careers/react-developer"><h3>React Developer</h3></a><span class="location">Pune</span></li>
    <li class="job-item"><a href="/careers/devops-lead"><h3>DevOps Lead</h3></a><span class="location">Remote</span></li>
  </ul>
</section>
<footer><a href="/privacy">Privacy</a><a href="/terms">Terms</a></footer>
</body></html>
"""

NAV_ONLY_HTML = """
<html><body><nav>
<a href="/">Home</a><a href="/about">About</a><a href="/services">Services</a>
<a href="/contact">Contact</a><a href="/blog">Blog</a>
</nav><p>Welcome to our company.</p></body></html>
"""


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Senior Python Engineer", True),
        ("React Developer", True),
        ("Home", False),
        ("About Us", False),
        ("", False),
        ("x", False),  # too short
        ("word " * 20, False),  # too many words
    ],
)
def test_looks_like_job_title(text, expected):
    assert looks_like_job_title(text) is expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("/careers/react-developer", True),
        ("https://x.com/job/123", True),
        ("https://jobs.lever.co/acme/abc", True),
        ("/about", False),
        ("/", False),
        (None, False),
    ],
)
def test_looks_like_job_link(url, expected):
    assert looks_like_job_link(url) is expected


# ---------------------------------------------------------------------------
# infer_selectors
# ---------------------------------------------------------------------------


def test_infer_selectors_produces_working_spec():
    spec = infer_selectors(JOB_HTML, "https://acme.example/careers")
    assert spec is not None
    # Spec must satisfy the adapter's own validation contract.
    validate_selectors(spec)
    rows = extract_rows(JOB_HTML, spec, "https://acme.example/careers")
    assert len(rows) == 3
    titles = {r["title"] for r in rows}
    assert "Senior Python Engineer" in titles
    # apply_url absolutized against the page.
    assert all(r["apply_url"].startswith("https://acme.example/careers/") for r in rows)
    # location selector was auto-added (resolves for all rows).
    assert spec.get("location")
    assert all(r["location"] for r in rows)


def test_infer_selectors_declines_nav_only_page():
    assert infer_selectors(NAV_ONLY_HTML, "https://x.example/careers") is None


def test_infer_selectors_rejects_broad_selector_on_nav_heavy_page():
    """A generic list_item (bare <li>) must NOT match a nav-heavy page even if a
    couple of job links exist, because the stored spec would scrape the nav too."""
    html = """
    <ul>
      <li><a href="/blog">Blog</a></li>
      <li><a href="/about">About</a></li>
      <li><a href="/faq">FAQ</a></li>
      <li><a href="/contact">Contact</a></li>
      <li><a href="/services">Services</a></li>
      <li><a href="/careers/python-developer">Python Developer</a></li>
      <li><a href="/careers/qa-engineer">QA Engineer</a></li>
    </ul>
    """
    spec = infer_selectors(html, "https://x.example/careers")
    # Either no spec, or a spec that is not the bare-<li> broad match.
    if spec is not None:
        assert spec["list_item"] != "li"


def test_infer_selectors_declines_single_job_below_threshold():
    html = (
        '<ul class="job-list"><li class="job">'
        '<a href="/careers/only-one"><h3>Only One Engineer</h3></a></li></ul>'
    )
    # MIN_GOOD_ROWS is 2, so a lone posting isn't enough to infer confidently.
    assert infer_selectors(html, "https://x.example/careers") is None


# ---------------------------------------------------------------------------
# run_infer orchestration (httpx-mocked)
# ---------------------------------------------------------------------------


async def test_run_infer_updates_seeds_and_review(tmp_path, monkeypatch):
    seeds = tmp_path / "companies.json"
    seeds.write_text(
        json.dumps([
            {"name": "GoodCo", "careers_url": "https://goodco.example/careers",
             "ats_type": "custom", "ats_identifier": None, "country": "India"},
            {"name": "BadCo", "careers_url": "https://badco.example/careers",
             "ats_type": "custom", "ats_identifier": None, "country": "India"},
            # Should be skipped: not India.
            {"name": "USco", "careers_url": "https://usco.example/careers",
             "ats_type": "custom", "ats_identifier": None, "country": None},
            # Should be skipped: already has selectors.
            {"name": "HasSel", "careers_url": "https://hs.example/careers",
             "ats_type": "custom", "custom_selectors": {"list_item": ".x", "title": "h3", "apply_url": "a@href"},
             "country": "India"},
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "SEEDS", seeds)
    monkeypatch.setattr(mod, "INFERRED_CSV", tmp_path / "inferred.csv")
    monkeypatch.setattr(mod, "REVIEW_CSV", tmp_path / "review.csv")

    with respx.mock(assert_all_called=False) as router:
        router.get("https://goodco.example/careers").mock(
            return_value=httpx.Response(200, text=JOB_HTML)
        )
        router.get("https://badco.example/careers").mock(
            return_value=httpx.Response(200, text=NAV_ONLY_HTML)
        )
        code = await run_infer(
            all_custom=False, country="India", use_playwright=False, dry_run=False
        )
    assert code == 0

    rows = {r["name"]: r for r in json.loads(seeds.read_text(encoding="utf-8"))}
    # GoodCo got a valid spec applied.
    assert rows["GoodCo"].get("custom_selectors")
    validate_selectors(rows["GoodCo"]["custom_selectors"])
    assert rows["GoodCo"]["ats_type"] == "custom"
    # BadCo could not be inferred -> unchanged + in review list.
    assert not rows["BadCo"].get("custom_selectors")
    review = (tmp_path / "review.csv").read_text(encoding="utf-8")
    assert "BadCo" in review
    assert "GoodCo" not in review
    # USco (non-India) and HasSel (already has selectors) untouched.
    assert not rows["USco"].get("custom_selectors")
    assert rows["HasSel"]["custom_selectors"] == {"list_item": ".x", "title": "h3", "apply_url": "a@href"}


async def test_run_infer_refresh_clears_stale_selectors(tmp_path, monkeypatch):
    """In --refresh mode, a company that no longer infers has its stale spec cleared."""
    seeds = tmp_path / "companies.json"
    seeds.write_text(
        json.dumps([
            {"name": "StaleCo", "careers_url": "https://staleco.example/careers",
             "ats_type": "custom",
             "custom_selectors": {"list_item": ".old", "title": "h3", "apply_url": "a@href"},
             "country": "India"},
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "SEEDS", seeds)
    monkeypatch.setattr(mod, "INFERRED_CSV", tmp_path / "inferred.csv")
    monkeypatch.setattr(mod, "REVIEW_CSV", tmp_path / "review.csv")

    with respx.mock(assert_all_called=False) as router:
        # Page no longer has an inferable job list.
        router.get("https://staleco.example/careers").mock(
            return_value=httpx.Response(200, text=NAV_ONLY_HTML)
        )
        await run_infer(all_custom=False, country="India", use_playwright=False,
                        dry_run=False, refresh=True)

    row = json.loads(seeds.read_text(encoding="utf-8"))[0]
    assert row.get("custom_selectors") is None
    assert row["ats_type"] == "custom"


async def test_run_infer_dry_run_writes_nothing(tmp_path, monkeypatch):
    seeds = tmp_path / "companies.json"
    original = [
        {"name": "GoodCo", "careers_url": "https://goodco.example/careers",
         "ats_type": "custom", "ats_identifier": None, "country": "India"},
    ]
    seeds.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(mod, "SEEDS", seeds)
    monkeypatch.setattr(mod, "INFERRED_CSV", tmp_path / "inferred.csv")
    monkeypatch.setattr(mod, "REVIEW_CSV", tmp_path / "review.csv")

    with respx.mock(assert_all_called=False) as router:
        router.get("https://goodco.example/careers").mock(
            return_value=httpx.Response(200, text=JOB_HTML)
        )
        await run_infer(all_custom=False, country="India", use_playwright=False, dry_run=True)
    assert json.loads(seeds.read_text(encoding="utf-8")) == original
    assert (tmp_path / "inferred.csv").exists()
