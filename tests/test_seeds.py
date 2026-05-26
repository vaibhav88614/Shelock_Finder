"""Offline validation of seeds/companies.json.

Asserts that every seed entry:
  * has the required keys
  * uses a registered ats_type
  * its declared ats_type matches what detect_ats() returns from careers_url
    (custom rows are exempt)
  * names are unique
  * there are at least 200 entries
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.adapters import ADAPTERS
from backend.config import settings
from backend.detect import detect_ats

REQUIRED_KEYS = {"name", "careers_url", "ats_type"}


@pytest.fixture(scope="module")
def seeds() -> list[dict]:
    path: Path = settings.seeds_dir / "companies.json"
    assert path.exists(), f"missing seed file: {path}"
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    return rows


def test_seed_minimum_count(seeds: list[dict]) -> None:
    assert len(seeds) >= 200, f"need >=200 seeds, found {len(seeds)}"


def test_seed_required_keys(seeds: list[dict]) -> None:
    for row in seeds:
        missing = REQUIRED_KEYS - row.keys()
        assert not missing, f"{row.get('name')!r} missing keys: {missing}"


def test_seed_unique_names(seeds: list[dict]) -> None:
    names = [r["name"] for r in seeds]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"duplicate seed names: {sorted(dupes)}"


def test_seed_ats_types_registered(seeds: list[dict]) -> None:
    unknown = sorted({r["ats_type"] for r in seeds if r["ats_type"] not in ADAPTERS})
    assert not unknown, f"ats_type values not in adapter registry: {unknown}"


def test_seed_detect_agrees(seeds: list[dict]) -> None:
    """detect_ats() must classify each non-custom row consistent with its declared ats_type."""
    mismatches: list[str] = []
    for row in seeds:
        declared = row["ats_type"]
        if declared == "custom":
            continue
        detected_type, _ = detect_ats(row["careers_url"])
        if detected_type != declared:
            mismatches.append(
                f"{row['name']!r}: declared={declared} detected={detected_type} url={row['careers_url']}"
            )
    assert not mismatches, "detect_ats disagrees with seed:\n  " + "\n  ".join(mismatches)


def test_seed_workday_identifier_format(seeds: list[dict]) -> None:
    """Workday identifiers must be 'host|tenant|site'."""
    for row in seeds:
        if row["ats_type"] != "workday":
            continue
        ident = row.get("ats_identifier") or ""
        parts = ident.split("|")
        assert len(parts) == 3, f"{row['name']!r}: workday identifier must be host|tenant|site, got {ident!r}"
        assert all(parts), f"{row['name']!r}: empty segment in workday identifier {ident!r}"
