"""Lever ATS adapter.

Public JSON endpoint, no auth required:
    https://api.lever.co/v0/postings/<co>?mode=json

Response is a top-level JSON array (NOT wrapped). Sample entry:
    {
      "id": "abc-uuid",
      "text": "Senior Backend Engineer",
      "hostedUrl": "https://jobs.lever.co/<co>/abc-uuid",
      "applyUrl":  "https://jobs.lever.co/<co>/abc-uuid/apply",
      "categories": {
          "location": "Remote - US",
          "commitment": "Full-time",
          "team": "Engineering",
          "department": "R&D",
          "allLocations": ["Remote - US", "New York"]
      },
      "createdAt": 1716480000000,          # epoch milliseconds
      "descriptionPlain": "...",
      "description": "<p>HTML...</p>",
      "lists": [{"text": "Requirements", "content": "<ul>...</ul>"}],
      "additionalPlain": "...",
      "workplaceType": "remote"            # may be absent
    }

The Lever account slug lives in `company.ats_identifier` (e.g. "netflix").
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger

from ._experience import parse_experience
from .base import AdapterError, BaseAdapter, NormalizedJob, RawJob


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str | None) -> str | None:
    if not s:
        return s
    return html.unescape(_TAG_RE.sub(" ", s)).strip()


def _coerce_workplace(raw_workplace: Any, location: str | None) -> str | None:
    if isinstance(raw_workplace, str) and raw_workplace.strip():
        v = raw_workplace.strip().lower()
        if v in {"remote", "hybrid", "onsite", "on-site"}:
            return "onsite" if v == "on-site" else v
    if location and re.search(r"\bremote\b", location, re.IGNORECASE):
        return "remote"
    if location and re.search(r"\bhybrid\b", location, re.IGNORECASE):
        return "hybrid"
    return None


class LeverAdapter(BaseAdapter):
    ats_type = "lever"
    BASE_URL = "https://api.lever.co/v0/postings"

    async def fetch(self, company) -> list[RawJob]:  # noqa: ANN001
        slug = (company.ats_identifier or "").strip()
        if not slug:
            raise AdapterError(
                f"Lever adapter requires ats_identifier on company {company.name!r}"
            )
        url = f"{self.BASE_URL}/{slug}?mode=json"
        try:
            resp = await self.request_with_retry("GET", url)
        except httpx.HTTPError as e:
            raise AdapterError(f"Lever fetch failed for {slug!r}: {e}") from e
        if resp.status_code == 404:
            raise AdapterError(f"Lever board {slug!r} not found (404)")
        if resp.status_code >= 400:
            raise AdapterError(
                f"Lever {slug!r} returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except ValueError as e:
            raise AdapterError(f"Lever {slug!r} returned non-JSON: {e}") from e
        if not isinstance(data, list):
            raise AdapterError(f"Lever {slug!r} expected JSON array, got {type(data).__name__}")
        logger.debug("Lever[{}]: {} jobs", slug, len(data))
        return data

    def normalize(self, raw: RawJob, company) -> NormalizedJob:  # noqa: ANN001
        external_id = raw.get("id")
        external_id = str(external_id) if external_id is not None else None
        title = (raw.get("text") or "").strip()
        apply_url = (raw.get("hostedUrl") or raw.get("applyUrl") or "").strip()

        cats = raw.get("categories") or {}
        if not isinstance(cats, dict):
            cats = {}

        location = (cats.get("location") or "").strip() or None
        department = (cats.get("team") or cats.get("department") or "").strip() or None
        employment_type = (cats.get("commitment") or "").strip() or None

        # Prefer plain description text; fall back to stripping HTML.
        description = raw.get("descriptionPlain")
        if not description:
            description = _strip_html(raw.get("description"))
        # Append additionalPlain (often contains "Requirements") for keyword/exp parsing.
        extra = raw.get("additionalPlain")
        if extra:
            description = f"{description or ''}\n\n{extra}".strip()

        posted_date: datetime | None = None
        ts = raw.get("createdAt")
        if isinstance(ts, (int, float)) and ts > 0:
            # Lever returns ms since epoch.
            try:
                posted_date = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).replace(tzinfo=None)
            except (OverflowError, OSError, ValueError):
                posted_date = None

        remote_type = _coerce_workplace(raw.get("workplaceType"), location)

        exp_min, exp_max = parse_experience(
            " ".join(filter(None, [title, description or ""]))[:5000]
        )

        return NormalizedJob(
            external_id=external_id,
            title=title,
            apply_url=apply_url,
            description=description,
            location=location,
            remote_type=remote_type,
            department=department,
            employment_type=employment_type,
            experience_min=exp_min,
            experience_max=exp_max,
            posted_date=posted_date,
            raw_payload=raw if isinstance(raw, dict) else {},
        )
