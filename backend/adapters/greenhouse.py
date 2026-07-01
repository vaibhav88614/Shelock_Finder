"""Greenhouse ATS adapter.

Public JSON endpoint, no auth required:
    https://boards-api.greenhouse.io/v1/boards/<board_token>/jobs?content=true

Response shape (abbreviated, see fixtures for a real sample):
    {
      "jobs": [
        {
          "id": 1234567,
          "internal_job_id": 999,
          "title": "Senior Software Engineer",
          "updated_at": "2026-05-20T17:33:48-04:00",
          "requisition_id": "REQ-42",
          "location": {"name": "San Francisco, CA"},
          "absolute_url": "https://boards.greenhouse.io/stripe/jobs/1234567",
          "metadata": [...],
          "content": "<p>HTML description...</p>",
          "departments": [{"id": 1, "name": "Engineering"}],
          "offices":     [{"id": 1, "name": "San Francisco"}]
        },
        ...
      ],
      "meta": {"total": 123}
    }

The board token lives in `company.ats_identifier` (e.g. "stripe").
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

import httpx
from dateutil import parser as dateparser
from loguru import logger

from ._experience import parse_experience
from .base import AdapterError, BaseAdapter, NormalizedJob, RawJob


_TAG_RE = re.compile(r"<[^>]+>")
_REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)
_HYBRID_RE = re.compile(r"\bhybrid\b", re.IGNORECASE)


def _strip_html(s: str | None) -> str | None:
    if not s:
        return s
    return html.unescape(_TAG_RE.sub(" ", s)).strip()


def _detect_remote_type(location: str | None, description: str | None) -> str | None:
    haystack = " ".join(filter(None, [location or "", (description or "")[:2000]]))
    if not haystack:
        return None
    if _REMOTE_RE.search(haystack):
        return "remote"
    if _HYBRID_RE.search(haystack):
        return "hybrid"
    return None


class GreenhouseAdapter(BaseAdapter):
    ats_type = "greenhouse"
    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    async def fetch(self, company) -> list[RawJob]:  # noqa: ANN001
        token = (company.ats_identifier or "").strip()
        if not token:
            raise AdapterError(
                f"Greenhouse adapter requires ats_identifier (board token) on company {company.name!r}"
            )
        url = f"{self.BASE_URL}/{token}/jobs?content=true"
        try:
            resp = await self.request("GET", url)
        except httpx.HTTPError as e:
            raise AdapterError(f"Greenhouse fetch failed for {token!r}: {e}") from e
        if resp.status_code == 404:
            raise AdapterError(f"Greenhouse board {token!r} not found (404)")
        if resp.status_code >= 400:
            raise AdapterError(
                f"Greenhouse {token!r} returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except ValueError as e:
            raise AdapterError(f"Greenhouse {token!r} returned non-JSON: {e}") from e

        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            raise AdapterError(f"Greenhouse {token!r} response missing 'jobs' list")
        logger.debug("Greenhouse[{}]: {} jobs", token, len(jobs))
        return jobs

    def normalize(self, raw: RawJob, company) -> NormalizedJob:  # noqa: ANN001
        external_id = str(raw.get("id")) if raw.get("id") is not None else None
        title = (raw.get("title") or "").strip()
        apply_url = (raw.get("absolute_url") or "").strip()
        location = None
        loc_obj = raw.get("location")
        if isinstance(loc_obj, dict):
            location = (loc_obj.get("name") or "").strip() or None
        elif isinstance(loc_obj, str):
            location = loc_obj.strip() or None

        description = _strip_html(raw.get("content"))

        department = None
        depts = raw.get("departments") or []
        if isinstance(depts, list) and depts:
            first = depts[0]
            if isinstance(first, dict):
                department = (first.get("name") or "").strip() or None

        # Greenhouse `metadata` can include {name: "Employment Type", value: "Full Time"}
        employment_type: str | None = None
        meta = raw.get("metadata") or []
        if isinstance(meta, list):
            for entry in meta:
                if not isinstance(entry, dict):
                    continue
                name = (entry.get("name") or "").lower()
                if name in {"employment type", "job type", "type"}:
                    val = entry.get("value")
                    if isinstance(val, str) and val.strip():
                        employment_type = val.strip()
                        break

        posted_date: datetime | None = None
        for key in ("first_published", "updated_at", "created_at"):
            v = raw.get(key)
            if isinstance(v, str) and v:
                try:
                    dt = dateparser.parse(v)
                    posted_date = dt.replace(tzinfo=None) if dt.tzinfo else dt
                    break
                except (ValueError, TypeError):
                    continue

        exp_min, exp_max = parse_experience(
            " ".join(filter(None, [title, description or ""]))[:5000]
        )

        return NormalizedJob(
            external_id=external_id,
            title=title,
            apply_url=apply_url,
            description=description,
            location=location,
            remote_type=_detect_remote_type(location, description),
            department=department,
            employment_type=employment_type,
            experience_min=exp_min,
            experience_max=exp_max,
            posted_date=posted_date,
            raw_payload=raw if isinstance(raw, dict) else {},
        )
