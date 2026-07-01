"""Workable adapter pagination + 5000-cap warning tests.

The base `test_phase5_adapters.py::test_workable_happy` covers a single-page
happy path. This file extends with:

  - Token-chained pagination across 3 pages.
  - The 5000-job safety cap fires `logger.warning(...)` once when actually
    triggered (Phase 2.7).
"""
from __future__ import annotations

import httpx
import pytest
import respx

from backend.adapters import WorkableAdapter


WORKABLE_URL = "https://apply.workable.com/api/v3/accounts/testlyft/jobs"


def _page(start: int, n: int, next_token: str | None) -> httpx.Response:
    """Build a Workable-shaped response with `n` synthetic jobs starting at `start`."""
    body: dict = {
        "results": [
            {
                "id": f"j-{start + i}",
                "shortcode": f"S{start + i}",
                "title": f"Test Engineer {start + i}",
                "url": f"https://apply.workable.com/testlyft/j/S{start + i}",
                "location": {"city": "", "region": "", "country": ""},
            }
            for i in range(n)
        ],
        "total": start + n + (1 if next_token else 0),
    }
    if next_token:
        body["nextPage"] = next_token
    return httpx.Response(200, json=body)


@respx.mock
async def test_workable_paginates_through_token_chain(fake_company):
    """3 pages of 10 jobs each, then no token → adapter returns all 30 jobs."""
    respx.post(WORKABLE_URL).mock(
        side_effect=[
            _page(0, 10, "tok-2"),
            _page(10, 10, "tok-3"),
            _page(20, 10, None),
        ]
    )

    adapter = WorkableAdapter()
    try:
        raws = await adapter.fetch(
            fake_company(ats_type="workable", ats_identifier="testlyft")
        )
        assert len(raws) == 30
        # Sanity: distinct ids, ordered as appended (pages → page → page).
        ids = [r["id"] for r in raws]
        assert ids[0] == "j-0"
        assert ids[10] == "j-10"
        assert ids[29] == "j-29"
    finally:
        await adapter.aclose()


@respx.mock
async def test_workable_5000_cap_warning_fires(fake_company, captured_logs):
    """When the 5000-job safety cap is hit, a single WARNING must be logged."""
    # Each page emits 2000 jobs. After page 3 (6000 total) the cap fires.
    respx.post(WORKABLE_URL).mock(
        side_effect=[
            _page(0, 2000, "tok-2"),
            _page(2000, 2000, "tok-3"),
            _page(4000, 2000, "tok-4"),  # cap fires before this token is followed
        ]
    )

    adapter = WorkableAdapter()
    try:
        raws = await adapter.fetch(
            fake_company(ats_type="workable", ats_identifier="testlyft")
        )
        assert len(raws) >= 5000  # cap triggered
    finally:
        await adapter.aclose()

    cap_warnings = [m for m in captured_logs if "5000-job" in m and "truncated" in m]
    assert len(cap_warnings) == 1, (
        f"expected exactly one cap warning, got {len(cap_warnings)}: {captured_logs}"
    )


@respx.mock
async def test_workable_under_cap_emits_no_warning(fake_company, captured_logs):
    """A normal pagination under 5000 jobs must NOT log the cap warning."""
    respx.post(WORKABLE_URL).mock(
        side_effect=[
            _page(0, 100, "tok-2"),
            _page(100, 50, None),
        ]
    )

    adapter = WorkableAdapter()
    try:
        raws = await adapter.fetch(
            fake_company(ats_type="workable", ats_identifier="testlyft")
        )
        assert len(raws) == 150
    finally:
        await adapter.aclose()

    cap_warnings = [m for m in captured_logs if "5000-job" in m]
    assert cap_warnings == [], (
        f"cap warning fired unexpectedly: {cap_warnings}"
    )
