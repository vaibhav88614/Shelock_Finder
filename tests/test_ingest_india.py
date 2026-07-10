"""Tests for scripts/ingest_india.py.

Covers the pure helpers (URL cleaning, host normalization, ATS-link scanning,
GoodFirms card parsing, dedupe, minimal xlsx reader) and the network-facing
discovery / sanity-check / full-ingest flows (respx-mocked; no real network).
"""
from __future__ import annotations

import json

import httpx
import pytest
import respx

import scripts.ingest_india as mod
from scripts.ingest_india import (
    clean_url,
    dedupe_candidates,
    discover_careers,
    extract_ats_links,
    homepage_base,
    host_of,
    load_excel,
    parse_goodfirms_cards,
    run_ingest,
    sanity_check,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            "https://sdlccorp.com/?utm_source=good-firms&utm_medium=listing&utm_campaign=x",
            "https://sdlccorp.com/",
        ),
        ("example.com/careers?ref=abc&team=eng", "https://example.com/careers?team=eng"),
        ("https://foo.com/x#frag", "https://foo.com/x"),
        ("", ""),
    ],
)
def test_clean_url(raw, expected):
    assert clean_url(raw) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.SDLCcorp.com:443/path", "sdlccorp.com"),
        ("http://Foo.IO", "foo.io"),
        ("bar.com/x", "bar.com"),
        ("", ""),
    ],
)
def test_host_of(url, expected):
    assert host_of(url) == expected


def test_homepage_base_strips_path_and_tracking():
    assert homepage_base("https://www.foo.com/a/b?utm_source=x") == "https://www.foo.com"


def test_extract_ats_links_finds_known_families():
    html = (
        '<a href="https://boards.greenhouse.io/acme">Jobs</a>'
        '<a href="/about">About</a>'
        '<a href="https://jobs.lever.co/acme">Careers</a>'
        '<a href="mailto:x@y.com">mail</a>'
    )
    links = extract_ats_links(html, "https://acme.com")
    assert any("greenhouse" in l for l in links)
    assert any("lever" in l for l in links)
    assert not any("about" in l for l in links)


def test_parse_goodfirms_cards_pairs_name_and_site():
    html = (
        '<div class="c"><h3>Acme Labs</h3>'
        '<a href="https://acme.com/?utm_source=good-firms&utm_medium=listing">Visit Website</a></div>'
        '<div class="c"><h3>Beta Tech</h3>'
        '<a href="https://beta.io/?utm_source=good-firms">See Beta Tech Website</a></div>'
    )
    cards = parse_goodfirms_cards(html)
    assert ("Acme Labs", "https://acme.com/") in cards
    assert ("Beta Tech", "https://beta.io/") in cards


def test_load_excel_prefers_column_with_real_host(tmp_path, monkeypatch):
    """companyWebsite is often a relative /company/... path; altWebsite has the site."""
    rows = [
        # sponsored-style row: companyWebsite is the real external URL
        {"companyName": "Acme", "companyWebsite": "https://acme.com/?utm_source=x", "altWebsite": "https://acme.com/"},
        # common row: companyWebsite is a relative GoodFirms profile path
        {"companyName": "Beta", "companyWebsite": "/company/beta", "altWebsite": "https://beta.io/"},
        # unusable row: neither has a host
        {"companyName": "Gamma", "companyWebsite": "/company/gamma", "altWebsite": ""},
    ]
    monkeypatch.setattr(mod, "_read_xlsx", lambda _p: rows)
    out = load_excel(tmp_path / "x.xlsx")
    by_name = {c["name"]: c["homepage"] for c in out}
    assert by_name["Acme"] == "https://acme.com/?utm_source=x"
    assert by_name["Beta"] == "https://beta.io/"
    assert "Gamma" not in by_name  # no real host anywhere -> skipped


def test_dedupe_candidates_by_host():
    out = dedupe_candidates([
        {"name": "A", "homepage": "https://x.com"},
        {"name": "A2", "homepage": "https://www.x.com/y"},
        {"name": "B", "homepage": "https://z.com"},
    ])
    assert [c["name"] for c in out] == ["A", "B"]


# ---------------------------------------------------------------------------
# Careers discovery (respx-mocked)
# ---------------------------------------------------------------------------


async def test_discover_finds_ats_on_homepage():
    home = "https://acme.example"
    html = '<a href="https://boards.greenhouse.io/acme">Careers</a>'
    with respx.mock(assert_all_called=False) as router:
        router.get("https://acme.example/").mock(return_value=httpx.Response(200, text=html))
        async with httpx.AsyncClient() as client:
            res = await discover_careers(client, home)
    assert res == ("https://boards.greenhouse.io/acme", "greenhouse", "acme")


async def test_discover_falls_back_to_careers_path():
    home = "https://beta.example"
    with respx.mock(assert_all_called=False) as router:
        router.get("https://beta.example/").mock(
            return_value=httpx.Response(200, text="<a href='/about'>About</a>")
        )
        router.head("https://beta.example/careers").mock(return_value=httpx.Response(200))
        async with httpx.AsyncClient() as client:
            res = await discover_careers(client, home)
    assert res == ("https://beta.example/careers", "custom", None)


async def test_discover_returns_none_when_nothing_works():
    home = "https://gamma.example"
    with respx.mock(assert_all_called=False) as router:
        router.get("https://gamma.example/").mock(
            return_value=httpx.Response(200, text="<a href='/x'>x</a>")
        )
        router.head(url__regex=r"https://gamma\.example/.+").mock(
            return_value=httpx.Response(404)
        )
        router.get(url__regex=r"https://gamma\.example/.+").mock(
            return_value=httpx.Response(404)
        )
        async with httpx.AsyncClient() as client:
            res = await discover_careers(client, home)
    assert res is None


# ---------------------------------------------------------------------------
# 5x sanity check (respx-mocked; sleep patched to no-op)
# ---------------------------------------------------------------------------


@pytest.fixture
def no_sleep(monkeypatch):
    async def _fake(*_a, **_k):
        return None

    monkeypatch.setattr(mod.asyncio, "sleep", _fake)


async def test_sanity_passes_on_first_ok(no_sleep):
    url = "https://x.example/careers"
    with respx.mock(assert_all_called=False) as router:
        router.head(url).mock(return_value=httpx.Response(200))
        async with httpx.AsyncClient() as client:
            ok, note = await sanity_check(client, url, rounds=5, spacing_s=0)
    assert ok is True
    assert note.startswith("ok@1")


async def test_sanity_all_fail_drops(no_sleep):
    url = "https://x.example/careers"
    with respx.mock(assert_all_called=False) as router:
        router.head(url).mock(return_value=httpx.Response(500))
        router.get(url).mock(return_value=httpx.Response(500))
        async with httpx.AsyncClient() as client:
            ok, note = await sanity_check(client, url, rounds=5, spacing_s=0)
    assert ok is False
    assert "all-5-failed" in note


async def test_sanity_recovers_on_later_attempt(no_sleep):
    url = "https://x.example/careers"
    with respx.mock(assert_all_called=False) as router:
        router.head(url).mock(side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200),
        ])
        # HEAD 503 triggers a GET fallback in `_head_or_get`; keep it failing
        # for the first two rounds (the third round's HEAD 200 short-circuits).
        router.get(url).mock(return_value=httpx.Response(503))
        async with httpx.AsyncClient() as client:
            ok, note = await sanity_check(client, url, rounds=5, spacing_s=0)
    assert ok is True
    assert note.startswith("ok@3")


# ---------------------------------------------------------------------------
# Full run_ingest flow (respx-mocked; curated source injected)
# ---------------------------------------------------------------------------


async def test_run_ingest_keeps_and_drops(tmp_path, monkeypatch, no_sleep):
    seeds = tmp_path / "companies.json"
    seeds.write_text(
        json.dumps([
            {
                "name": "Existing",
                "careers_url": "https://boards.greenhouse.io/existing",
                "ats_type": "greenhouse",
                "ats_identifier": "existing",
            }
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "SEEDS", seeds)
    monkeypatch.setattr(mod, "REPORT_CSV", tmp_path / "report.csv")
    monkeypatch.setattr(mod, "DROPPED_CSV", tmp_path / "dropped.csv")

    def _fake_curated():
        return [
            {"name": "KeepCo", "homepage": "https://keepco.example", "source": "curated"},
            {"name": "DropCo", "homepage": "https://dropco.example", "source": "curated"},
        ]

    monkeypatch.setattr(mod, "load_curated", _fake_curated)

    with respx.mock(assert_all_called=False) as router:
        # KeepCo: homepage links to a greenhouse board that is reachable.
        router.get("https://keepco.example/").mock(
            return_value=httpx.Response(
                200, text='<a href="https://boards.greenhouse.io/keepco">Careers</a>'
            )
        )
        router.head("https://boards.greenhouse.io/keepco").mock(
            return_value=httpx.Response(200)
        )
        # DropCo: no ATS link, and every careers path 404s.
        router.get("https://dropco.example/").mock(
            return_value=httpx.Response(200, text="<a href='/about'>About</a>")
        )
        router.head(url__regex=r"https://dropco\.example/.+").mock(
            return_value=httpx.Response(404)
        )
        router.get(url__regex=r"https://dropco\.example/.+").mock(
            return_value=httpx.Response(404)
        )

        code = await run_ingest(
            from_excel=None,
            goodfirms_categories=[],
            from_curated=True,
            dry_run=False,
            sanity_rounds=5,
            sanity_spacing_s=0,
        )
    assert code == 0

    rows = json.loads(seeds.read_text(encoding="utf-8"))
    by_name = {r["name"]: r for r in rows}
    assert "Existing" in by_name  # preserved verbatim
    assert "KeepCo" in by_name
    assert by_name["KeepCo"]["country"] == "India"
    assert by_name["KeepCo"]["ats_type"] == "greenhouse"
    assert by_name["KeepCo"]["ats_identifier"] == "keepco"
    assert "DropCo" not in by_name  # dropped: all sanity attempts failed

    dropped = (tmp_path / "dropped.csv").read_text(encoding="utf-8")
    assert "DropCo" in dropped


async def test_run_ingest_dry_run_writes_nothing(tmp_path, monkeypatch, no_sleep):
    seeds = tmp_path / "companies.json"
    original = [{"name": "Existing", "careers_url": "https://x", "ats_type": "custom", "ats_identifier": None}]
    seeds.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(mod, "SEEDS", seeds)
    monkeypatch.setattr(mod, "REPORT_CSV", tmp_path / "report.csv")
    monkeypatch.setattr(mod, "DROPPED_CSV", tmp_path / "dropped.csv")
    monkeypatch.setattr(
        mod, "load_curated",
        lambda: [{"name": "KeepCo", "homepage": "https://keepco.example"}],
    )
    with respx.mock(assert_all_called=False) as router:
        router.get("https://keepco.example/").mock(
            return_value=httpx.Response(
                200, text='<a href="https://boards.greenhouse.io/keepco">Careers</a>'
            )
        )
        router.head("https://boards.greenhouse.io/keepco").mock(
            return_value=httpx.Response(200)
        )
        await run_ingest(
            from_excel=None, goodfirms_categories=[], from_curated=True,
            dry_run=True, sanity_rounds=5, sanity_spacing_s=0,
        )
    # Seeds unchanged on dry-run.
    assert json.loads(seeds.read_text(encoding="utf-8")) == original
    # But the report is still written.
    assert (tmp_path / "report.csv").exists()
