"""Retry/backoff behavior of BaseAdapter.request().

Uses respx to mock the Greenhouse endpoint (any adapter exercises the shared
`BaseAdapter.request`). `asyncio.sleep` is patched to a no-op so the tests run
instantly while still exercising the retry loop.
"""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import respx

from backend.adapters.base import AdapterError
from backend.adapters.greenhouse import GreenhouseAdapter


GH_URL = "https://boards-api.greenhouse.io/v1/boards/testco/jobs?content=true"


def _company():
    return SimpleNamespace(
        id=1, name="TestCo", ats_type="greenhouse",
        ats_identifier="testco", careers_url="https://boards.greenhouse.io/testco",
        custom_selectors=None,
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Make backoff instantaneous and record the delays requested."""
    delays: list[float] = []

    async def _fake_sleep(d):  # noqa: ANN001
        delays.append(d)

    monkeypatch.setattr("backend.adapters.base.asyncio.sleep", _fake_sleep)
    return delays


_GH_BODY = {"jobs": [{"id": 1, "title": "Engineer", "absolute_url": "https://x/1"}]}


async def test_retries_429_then_succeeds():
    a = GreenhouseAdapter()
    try:
        with respx.mock(assert_all_called=True) as router:
            route = router.get(GH_URL)
            route.side_effect = [
                httpx.Response(429),
                httpx.Response(429),
                httpx.Response(200, json=_GH_BODY),
            ]
            jobs = await a.fetch(_company())
        assert len(jobs) == 1
        assert route.call_count == 3
    finally:
        await a.aclose()


async def test_retries_503_then_succeeds():
    a = GreenhouseAdapter()
    try:
        with respx.mock(assert_all_called=True) as router:
            route = router.get(GH_URL)
            route.side_effect = [
                httpx.Response(503),
                httpx.Response(200, json=_GH_BODY),
            ]
            jobs = await a.fetch(_company())
        assert len(jobs) == 1
        assert route.call_count == 2
    finally:
        await a.aclose()


async def test_404_is_not_retried():
    a = GreenhouseAdapter()
    try:
        with respx.mock(assert_all_called=True) as router:
            route = router.get(GH_URL).mock(return_value=httpx.Response(404))
            with pytest.raises(AdapterError):
                await a.fetch(_company())
        assert route.call_count == 1  # terminal, no retry
    finally:
        await a.aclose()


async def test_exhausts_retries_then_raises():
    a = GreenhouseAdapter()
    try:
        with respx.mock(assert_all_called=True) as router:
            route = router.get(GH_URL).mock(return_value=httpx.Response(429))
            with pytest.raises(AdapterError):
                await a.fetch(_company())
        # initial try + MAX_RETRIES
        assert route.call_count == GreenhouseAdapter.MAX_RETRIES + 1
    finally:
        await a.aclose()


async def test_retry_after_header_respected(_no_sleep):
    a = GreenhouseAdapter()
    try:
        with respx.mock(assert_all_called=True) as router:
            route = router.get(GH_URL)
            route.side_effect = [
                httpx.Response(429, headers={"Retry-After": "1"}),
                httpx.Response(200, json=_GH_BODY),
            ]
            await a.fetch(_company())
        assert route.call_count == 2
        # The first (and only) sleep must reflect the Retry-After value.
        assert _no_sleep and _no_sleep[0] == pytest.approx(1.0, abs=0.001)
    finally:
        await a.aclose()


async def test_transport_error_is_retried():
    a = GreenhouseAdapter()
    try:
        with respx.mock(assert_all_called=True) as router:
            route = router.get(GH_URL)
            route.side_effect = [
                httpx.ConnectError("boom"),
                httpx.Response(200, json=_GH_BODY),
            ]
            jobs = await a.fetch(_company())
        assert len(jobs) == 1
        assert route.call_count == 2
    finally:
        await a.aclose()
