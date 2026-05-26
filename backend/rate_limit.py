"""Tiny async token-bucket rate limiter, keyed by ATS family.

The orchestrator instantiates one `RateLimiterGroup` per scrape run, looks up
the bucket by `company.ats_type`, and `await`s before each HTTP call. Buckets
defined here match the per-ATS limits in spec §6:

    Greenhouse:        10 req/s
    Workday:            2 req/s
    Everything else:    5 req/s

A bucket has integer capacity (burst size) and a refill rate in tokens/second.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    capacity: float
    refill_per_sec: float
    tokens: float
    last_refill: float
    lock: asyncio.Lock

    async def acquire(self, amount: float = 1.0) -> None:
        async with self.lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_refill
                if elapsed > 0:
                    self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
                    self.last_refill = now
                if self.tokens >= amount:
                    self.tokens -= amount
                    return
                # Sleep just long enough to gain the deficit.
                deficit = amount - self.tokens
                wait_s = max(deficit / self.refill_per_sec, 0.01)
                await asyncio.sleep(wait_s)


# Tuple is (capacity, refill_per_sec). Capacity = max burst.
DEFAULT_LIMITS: dict[str, tuple[float, float]] = {
    "greenhouse": (10.0, 10.0),
    "workday": (2.0, 2.0),
    "playwright": (1.0, 1.0),
    "default": (5.0, 5.0),
}


class RateLimiterGroup:
    """Lazy per-ATS bucket store. Thread-unsafe; use from a single event loop."""

    def __init__(self, limits: dict[str, tuple[float, float]] | None = None) -> None:
        self._limits = limits or DEFAULT_LIMITS
        self._buckets: dict[str, _Bucket] = {}

    def _bucket_for(self, ats_type: str) -> _Bucket:
        key = ats_type if ats_type in self._limits else "default"
        b = self._buckets.get(key)
        if b is None:
            cap, refill = self._limits[key]
            b = _Bucket(
                capacity=cap,
                refill_per_sec=refill,
                tokens=cap,  # start full so the first burst goes through
                last_refill=time.monotonic(),
                lock=asyncio.Lock(),
            )
            self._buckets[key] = b
        return b

    async def acquire(self, ats_type: str) -> None:
        await self._bucket_for(ats_type).acquire()
