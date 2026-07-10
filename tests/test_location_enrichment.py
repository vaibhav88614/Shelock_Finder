"""Tests for scrape-time location normalization (`backend.scrape._enrich_location`).

A company tagged with a `country` should have that country appended to any
scraped job location that doesn't already name a country/region, so the
existing free-text Location dashboard filter matches reliably. Companies with
no country (the default US/global seeds) must be left untouched.
"""
from __future__ import annotations

import pytest

from backend.scrape import _enrich_location


@pytest.mark.parametrize(
    "loc,country,expected",
    [
        # City-only strings get the country appended.
        ("Bangalore", "India", "Bangalore, India"),
        ("Mumbai", "India", "Mumbai, India"),
        ("Remote", "India", "Remote, India"),
        # Already geo-qualified -> untouched.
        ("Bengaluru, India", "India", "Bengaluru, India"),
        ("Remote - Worldwide", "India", "Remote - Worldwide"),
        ("San Francisco, USA", "India", "San Francisco, USA"),
        # Standalone short country codes recognized on word boundaries.
        ("Remote, US", "India", "Remote, US"),
        ("London, UK", "India", "London, UK"),
        # ...but the code must not fire inside an unrelated word.
        ("Business Bay, Dubai", "India", "Business Bay, Dubai, India"),
        # No country on the company -> never modified.
        ("Bangalore", None, "Bangalore"),
        ("Bangalore", "", "Bangalore"),
        # Empty / missing location on a country-tagged company -> the country
        # (so these jobs still match a Location=India filter).
        (None, "India", "India"),
        ("", "India", "India"),
        ("   ", "India", "India"),
        # No country + empty location -> passthrough.
        (None, None, None),
    ],
)
def test_enrich_location(loc, country, expected):
    assert _enrich_location(loc, country) == expected


def test_enrich_is_idempotent():
    once = _enrich_location("Pune", "India")
    twice = _enrich_location(once, "India")
    assert once == "Pune, India"
    assert twice == "Pune, India"


def test_enrich_case_insensitive_country_match():
    # Country already present in a different case must not be duplicated.
    assert _enrich_location("Delhi, INDIA", "India") == "Delhi, INDIA"
