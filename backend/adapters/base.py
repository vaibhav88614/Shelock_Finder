"""BaseAdapter contract + shared dataclasses.

Every ATS adapter (Greenhouse, Lever, Workday, ...) subclasses `BaseAdapter`
and implements `fetch()`. The orchestrator (phase 3) then:

    raws = await adapter.fetch(company)
    for raw in raws:
        normalized = adapter.normalize(raw)
        upsert(normalized)

Design notes
------------
* `RawJob` is whatever the adapter pulls out of its source (ATS JSON dict,
  scraped HTML element, etc.). We keep it `dict[str, Any]` so adapters don't
  have to invent dataclasses for every ATS quirk.
* `NormalizedJob` is the *one* shape the rest of the system depends on. All
  downstream code (dedupe, DB upsert, FTS, CSV export) reads only this.
* `fingerprint()` lives here so every adapter computes it the same way and
  the dedupe invariants in §4 of the spec hold across ATS families.
* `apply_url` is mandatory and is normalized (whitespace stripped, trailing
  slashes preserved as-is) so HTML-fallback adapters can't accidentally
  produce two different fingerprints for the same posting.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from ..config import settings


# Raw payload is intentionally a free-form dict — adapters know their shape.
RawJob = dict[str, Any]


@dataclass
class NormalizedJob:
    """The canonical job shape persisted to the DB."""

    external_id: str | None
    title: str
    apply_url: str
    description: str | None = None
    location: str | None = None
    remote_type: str | None = None  # "remote" | "hybrid" | "onsite" | None
    department: str | None = None
    employment_type: str | None = None  # "full-time" | "contract" | ...
    experience_min: int | None = None
    experience_max: int | None = None
    posted_date: datetime | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")


def _normalize_title(title: str) -> str:
    return _WS_RE.sub(" ", title.strip().lower())


def fingerprint(
    company_id: int,
    external_id: str | None,
    title: str,
    location: str | None,
    apply_url: str,
) -> str:
    """Stable SHA-256 fingerprint per spec §4.

    Preferred: `sha256(f"{company_id}::{external_id}")` when ATS provides ID.
    Fallback:  `sha256(f"{company_id}::{title}::{location}::{apply_url}")`
               using normalized title.
    """
    if external_id:
        key = f"{company_id}::{external_id}"
    else:
        key = (
            f"{company_id}::{_normalize_title(title)}"
            f"::{(location or '').strip().lower()}"
            f"::{apply_url.strip()}"
        )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# BaseAdapter
# ---------------------------------------------------------------------------


class AdapterError(Exception):
    """Raised by an adapter when fetching/parsing fails permanently for a company.

    The orchestrator catches this per-company so one broken site never aborts
    a whole run.
    """


class BaseAdapter(ABC):
    """Subclass me to add a new ATS.

    Required class attributes
    -------------------------
    ats_type : str
        Short identifier persisted in `companies.ats_type` (e.g. "greenhouse").
    """

    ats_type: str = ""

    # -- Retry policy (shared by every adapter's HTTP calls) ---------------
    # Retry transient throttling / server errors; 404 and other 4xx are
    # terminal and never retried. Retry-After (seconds form) is honored but
    # capped.
    #
    # INVARIANT (see backend/scrape.py PER_COMPANY_TIMEOUT_S = 60s): the total
    # time spent *sleeping* between retries must stay well under the
    # orchestrator's per-company timeout, or `asyncio.wait_for` would kill the
    # coroutine mid-retry and under-count that company's jobs. Worst case is
    #   MAX_RETRIES * max(BACKOFF_CAP_S, RETRY_AFTER_CAP_S) = 3 * 10 = 30s < 60s,
    # leaving headroom for the actual request round-trips.
    RETRY_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
    MAX_RETRIES: int = 3
    BACKOFF_BASE_S: float = 0.5
    BACKOFF_CAP_S: float = 8.0
    RETRY_AFTER_CAP_S: float = 10.0

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        # The orchestrator passes in a shared client so connection pooling
        # works across companies. Tests can omit it; we lazily create one.
        self._client = client
        self._owns_client = client is None
        # Optional zero-arg async callable that re-acquires this ATS family's
        # rate-limit token. The orchestrator sets it so retries back off
        # *politely* (a server already 429ing shouldn't be hammered). None in
        # tests / standalone use, where no global limiter exists.
        self._rate_acquire: Callable[[], Awaitable[None]] | None = None

    # -- HTTP plumbing ------------------------------------------------------

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- Resilient request wrapper -----------------------------------------

    def _backoff_delay(self, attempt: int) -> float:
        """Full-jitter exponential backoff for retry `attempt` (0-indexed)."""
        ceiling = min(self.BACKOFF_CAP_S, self.BACKOFF_BASE_S * (2 ** attempt))
        return ceiling + random.uniform(0.0, self.BACKOFF_BASE_S)

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> float | None:
        """Return the Retry-After delay in seconds if given as an integer.

        HTTP-date forms return None (we fall back to computed backoff).
        """
        raw = resp.headers.get("Retry-After")
        if not raw:
            return None
        try:
            secs = float(raw.strip())
        except ValueError:
            return None
        return secs if secs >= 0 else None

    async def request_with_retry(
        self, method: str, url: str, *, retry: bool = True, **kwargs: Any
    ) -> httpx.Response:
        """Issue an HTTP request with retry on 429/5xx and transport errors.

        Non-retryable responses (2xx, 3xx, 404, other 4xx) are returned to the
        caller unchanged so existing per-adapter status handling still applies.

        IDEMPOTENCY: retries re-send the request verbatim, so this is only safe
        for idempotent calls. Every adapter here uses GET, or POST against a
        *read-only search* endpoint (Workable/Workday job listings). A future
        adapter that issues a state-changing POST MUST pass ``retry=False`` to
        opt out, otherwise a transient 5xx could double-fire the mutation.

        On each retry attempt the ATS rate-limit bucket is re-acquired (when the
        orchestrator wired one in) so a throttled server is not hammered.
        """
        max_retries = self.MAX_RETRIES if retry else 0
        attempt = 0
        while True:
            try:
                resp = await self.client.request(method, url, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= max_retries:
                    raise
                delay = self._backoff_delay(attempt)
                logger.debug(
                    "{} {} transport error ({}); retry {}/{} in {:.2f}s",
                    method, url, type(exc).__name__, attempt + 1, max_retries, delay,
                )
                await asyncio.sleep(delay)
                await self._reacquire_rate_token()
                attempt += 1
                continue

            if resp.status_code in self.RETRY_STATUSES and attempt < max_retries:
                retry_after = self._parse_retry_after(resp)
                delay = (
                    min(retry_after, self.RETRY_AFTER_CAP_S)
                    if retry_after is not None
                    else self._backoff_delay(attempt)
                )
                logger.debug(
                    "{} {} -> HTTP {}; retry {}/{} in {:.2f}s",
                    method, url, resp.status_code, attempt + 1, max_retries, delay,
                )
                await asyncio.sleep(delay)
                await self._reacquire_rate_token()
                attempt += 1
                continue

            return resp

    async def _reacquire_rate_token(self) -> None:
        """Re-acquire the per-ATS rate-limit token before a retry, if wired."""
        if self._rate_acquire is not None:
            await self._rate_acquire()

    # -- Contract -----------------------------------------------------------

    @abstractmethod
    async def fetch(self, company) -> list[RawJob]:  # noqa: ANN001 — Company forward ref
        """Pull every active posting for `company`. May raise AdapterError."""

    @abstractmethod
    def normalize(self, raw: RawJob, company) -> NormalizedJob:  # noqa: ANN001
        """Convert a single raw entry into a NormalizedJob."""

    # -- Convenience --------------------------------------------------------

    def fingerprint_for(self, company_id: int, normalized: NormalizedJob) -> str:
        return fingerprint(
            company_id=company_id,
            external_id=normalized.external_id,
            title=normalized.title,
            location=normalized.location,
            apply_url=normalized.apply_url,
        )
