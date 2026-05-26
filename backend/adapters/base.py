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

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

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

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        # The orchestrator passes in a shared client so connection pooling
        # works across companies. Tests can omit it; we lazily create one.
        self._client = client
        self._owns_client = client is None

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
