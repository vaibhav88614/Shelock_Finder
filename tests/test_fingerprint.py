"""Tests for `adapters.base.fingerprint`."""
from __future__ import annotations

from backend.adapters.base import fingerprint


def test_fingerprint_prefers_external_id():
    a = fingerprint(1, "abc", "Engineer", "SF", "https://x/y")
    b = fingerprint(1, "abc", "Different Title", "NYC", "https://x/z")
    assert a == b, "external_id path must ignore other fields"


def test_fingerprint_falls_back_to_title_location_url():
    a = fingerprint(1, None, "Engineer", "SF", "https://x/y")
    b = fingerprint(1, None, "Engineer", "SF", "https://x/y")
    c = fingerprint(1, None, "engineer  ", "sf", "https://x/y")  # normalized title
    assert a == b
    assert a == c, "title is normalized (lower + collapsed whitespace)"


def test_fingerprint_changes_on_any_field_when_no_external_id():
    base = fingerprint(1, None, "Engineer", "SF", "https://x/y")
    assert fingerprint(2, None, "Engineer", "SF", "https://x/y") != base
    assert fingerprint(1, None, "Engineer 2", "SF", "https://x/y") != base
    assert fingerprint(1, None, "Engineer", "NYC", "https://x/y") != base
    assert fingerprint(1, None, "Engineer", "SF", "https://x/z") != base


def test_fingerprint_is_64_char_hex():
    fp = fingerprint(1, "abc", "x", "y", "z")
    assert len(fp) == 64
    int(fp, 16)  # raises if not hex
