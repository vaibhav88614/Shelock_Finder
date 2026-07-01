"""Token-bucket rate limiter unit tests.

Covers `backend.rate_limit.RateLimiterGroup`:

  - Bucket starts full so the first burst passes without sleeping.
  - Unknown ATS keys fall back to the `"default"` bucket.
  - After exhausting tokens, `acquire()` waits roughly `1 / refill_per_sec`
    seconds for the next token.
  - Lazy per-key bucket creation does not blow up.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from backend.rate_limit import RateLimiterGroup


@pytest.mark.asyncio
async def test_initial_burst_does_not_block():
    """`capacity` consecutive `acquire`s must complete almost instantly."""
    rl = RateLimiterGroup({"greenhouse": (5.0, 5.0)})
    t0 = time.monotonic()
    for _ in range(5):
        await rl.acquire("greenhouse")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.05, f"initial burst slept unexpectedly: {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_unknown_ats_falls_back_to_default():
    """An unregistered key uses the `'default'` limits."""
    rl = RateLimiterGroup({"default": (3.0, 3.0)})
    for _ in range(3):
        await rl.acquire("never-heard-of-this")
    # If the fallback had failed, the 4th acquire below would deadlock — gate
    # with a timeout so the test fails loudly instead of hanging.
    t0 = time.monotonic()
    await asyncio.wait_for(rl.acquire("never-heard-of-this"), timeout=1.0)
    # 4th token: bucket was empty (cap=3), refill=3/s → ~0.33s wait.
    elapsed = time.monotonic() - t0
    assert 0.2 < elapsed < 0.6, f"unexpected wait for 4th token: {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_drains_then_refills_at_configured_rate():
    """After draining, the next `acquire` waits ~ 1/refill_per_sec seconds."""
    # cap=2 → first 2 are free; refill=5/s → next costs ~0.2s.
    rl = RateLimiterGroup({"x": (2.0, 5.0)})
    await rl.acquire("x")
    await rl.acquire("x")
    t0 = time.monotonic()
    await rl.acquire("x")
    elapsed = time.monotonic() - t0
    assert 0.15 < elapsed < 0.4, f"unexpected refill wait: {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_separate_keys_have_independent_buckets():
    """Draining bucket A must not block acquires on bucket B."""
    rl = RateLimiterGroup({"a": (1.0, 1.0), "b": (1.0, 1.0)})
    await rl.acquire("a")  # drains 'a'
    t0 = time.monotonic()
    await rl.acquire("b")  # 'b' bucket is still full → instant
    elapsed = time.monotonic() - t0
    assert elapsed < 0.05, f"bucket isolation broken: {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_concurrent_acquires_serialize_correctly():
    """Concurrent `acquire`s on the same bucket should not all bypass the limit."""
    rl = RateLimiterGroup({"y": (2.0, 10.0)})  # cap 2, refill 10/s → 0.1s per
    t0 = time.monotonic()
    # 6 concurrent acquires: first 2 are free, next 4 wait ~0.1s, 0.2s, 0.3s, 0.4s.
    await asyncio.gather(*(rl.acquire("y") for _ in range(6)))
    elapsed = time.monotonic() - t0
    # At least ~0.4s for the last token (4 × 0.1s sequential refills).
    assert elapsed > 0.3, f"rate limit not enforced under concurrency: {elapsed:.3f}s"
