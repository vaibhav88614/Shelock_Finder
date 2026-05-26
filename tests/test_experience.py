"""Tests for `_experience.parse_experience`."""
from __future__ import annotations

import pytest

from backend.adapters._experience import parse_experience


@pytest.mark.parametrize(
    "text, expected",
    [
        # Ranges
        ("Requires 3-5 years of experience", (3, 5)),
        ("3 to 5 years experience required", (3, 5)),
        ("Minimum 5–8 years industry experience", (5, 8)),
        # Plus / minimum / at-least
        ("3+ years of experience", (3, None)),
        ("minimum 2 years experience required", (2, None)),
        ("at least 4 years of professional experience", (4, None)),
        ("5 or more years of relevant experience", (5, None)),
        # Up-to
        ("Up to 7 years of experience considered", (None, 7)),
        # Single
        ("2 years experience required", (2, 2)),
        ("Looking for someone with 4 years of experience", (4, 4)),
        # Misses
        ("No prior industry experience required.", (None, None)),
        ("", (None, None)),
        (None, (None, None)),
        ("Entry-level role for recent graduates.", (None, None)),
    ],
)
def test_parse_experience(text, expected):
    assert parse_experience(text) == expected


def test_parse_experience_caps_unreasonable_values():
    # 99 years is silly; parser should ignore (range/min/single all bounded 0-30).
    assert parse_experience("99 years experience") == (None, None)
    assert parse_experience("50-60 years experience") == (None, None)
