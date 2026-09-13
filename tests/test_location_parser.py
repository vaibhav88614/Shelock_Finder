"""Unit tests for the location parser.

Focuses on the two things the API depends on: correct ``ParsedLocation``
values for well-formed ATS strings and safe pass-through (no false
positives) for messy edge cases.
"""
from __future__ import annotations

import pytest

from backend.location import canonical_country, known_countries, parse_location


@pytest.mark.parametrize(
    "raw,expected_city,expected_country,is_remote",
    [
        # Basic city, country
        ("Bengaluru, India", "Bengaluru", "India", False),
        ("Mumbai, India", "Mumbai", "India", False),
        ("Bangalore, KA", "Bengaluru", "India", False),  # alias canonicalises
        ("Bombay, MH, India", "Mumbai", "India", False),  # ditto
        ("San Francisco, CA", "San Francisco", "United States", False),
        ("NYC, NY", "New York", "United States", False),
        ("London, UK", "London", "United Kingdom", False),
        ("Berlin, Germany", "Berlin", "Germany", False),
        ("Amsterdam", "Amsterdam", "Netherlands", False),
        # Country only (no city)
        ("United States", None, "United States", False),
        ("India", None, "India", False),
        ("U.S.A.", None, "United States", False),
        # Remote variations
        ("Remote", None, None, True),
        ("Remote - US", None, "United States", True),
        ("Remote (India)", None, "India", True),
        ("Work from home", None, None, True),
        ("WFH", None, None, True),
        # Hybrid should NOT be flagged remote
        ("Hybrid - Bengaluru", "Bengaluru", "India", False),
        ("Berlin (hybrid)", "Berlin", "Germany", False),
    ],
)
def test_parse_common_locations(raw, expected_city, expected_country, is_remote):
    p = parse_location(raw, None)
    assert p.city == expected_city, raw
    assert p.country == expected_country, raw
    assert p.is_remote is is_remote, raw


def test_parse_uses_company_country_when_ambiguous():
    """Empty / unrecognised strings fall back to the company hint."""
    assert parse_location("", "India").country == "India"
    assert parse_location(None, "India").country == "India"
    # An unrecognized location string with a company hint — parser can't
    # find a city but should apply the hint.
    p = parse_location("Some obscure office", "India")
    assert p.country == "India"
    assert p.city is None
    # A recognised country should NOT be overwritten by the hint.
    assert parse_location("Berlin", "India").country == "Germany"


def test_parse_us_state_region():
    p = parse_location("Austin, TX", None)
    assert p.city == "Austin"
    assert p.country == "United States"
    assert p.region == "Texas"


def test_word_boundary_no_false_positives():
    """"Berlin Heights, OH" must not pick up Berlin/Germany."""
    p = parse_location("Berlin Heights, OH", None)
    # Neither "Berlin" as a bare city nor "OH" (Ohio) is currently in the
    # curated cities table, so both come back empty — the important
    # invariant is that we don't wrongly claim Germany.
    assert p.country != "Germany"


def test_remote_pure_but_hybrid_wins():
    """"Remote/Hybrid" is intentionally ambiguous; hybrid takes precedence."""
    p = parse_location("Remote / Hybrid — Berlin", None)
    assert p.is_remote is False
    assert p.city == "Berlin"


def test_empty_string():
    p = parse_location("", None)
    assert p.is_empty
    assert p.is_remote is False


def test_known_countries_contains_expected():
    known = set(known_countries())
    for c in ("India", "United States", "United Kingdom", "Germany", "Australia"):
        assert c in known


def test_canonical_country_aliases():
    assert canonical_country("US") == "United States"
    assert canonical_country("UK") == "United Kingdom"
    assert canonical_country("holland") == "Netherlands"
    assert canonical_country("Deutschland") == "Germany"
    assert canonical_country("") is None
    assert canonical_country(None) is None
    assert canonical_country("Zzz") is None
