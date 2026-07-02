"""Ashby ATS adapter.

Public REST endpoint, no auth required:
    https://api.ashbyhq.com/posting-api/job-board/<org>?includeCompensation=false

Returns `{apiVersion, jobs: [{id, title, location, locationIds, employmentType,
isListed, descriptionHtml, descriptionPlain, jobUrl, department, team,
publishedAt, address, ...}]}` — everything we need in one call.

`ats_identifier` is the Ashby organization slug.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from dateutil import parser as dateparser
from loguru import logger

from ._experience import parse_experience
from ._text import detect_remote_type, strip_html
from .base import AdapterError, BaseAdapter, NormalizedJob, RawJob


class AshbyAdapter(BaseAdapter):
    ats_type = "ashby"
    BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"

    async def fetch(self, company) -> list[RawJob]:  # noqa: ANN001
        org = (company.ats_identifier or "").strip()
        if not org:
            raise AdapterError(
                f"Ashby adapter requires ats_identifier on company {company.name!r}"
            )
        url = f"{self.BASE_URL}/{org}?includeCompensation=false"
        try:
            resp = await self.request_with_retry("GET", url)
        except httpx.HTTPError as e:
            raise AdapterError(f"Ashby fetch failed for {org!r}: {e}") from e
        if resp.status_code == 404:
            raise AdapterError(f"Ashby org {org!r} not found (404)")
        if resp.status_code >= 400:
            raise AdapterError(f"Ashby {org!r} HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as e:
            raise AdapterError(f"Ashby {org!r} non-JSON: {e}") from e
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            raise AdapterError(f"Ashby {org!r} response missing 'jobs' list")
        # Honor isListed flag (Ashby leaves drafts in the feed).
        jobs = [j for j in jobs if not isinstance(j, dict) or j.get("isListed", True)]
        logger.debug("Ashby[{}]: {} jobs", org, len(jobs))
        return jobs

    def normalize(self, raw: RawJob, company) -> NormalizedJob:  # noqa: ANN001
        external_id = raw.get("id")
        external_id = str(external_id) if external_id is not None else None
        title = (raw.get("title") or "").strip()
        apply_url = (raw.get("jobUrl") or raw.get("applyUrl") or "").strip()

        location = (raw.get("location") or "").strip() or None
        # `address` is sometimes a richer dict
        if not location:
            addr = raw.get("address") or {}
            if isinstance(addr, dict):
                parts = [addr.get(k) for k in ("postalAddress", "addressRegion", "addressCountry")]
                location = ", ".join(p for p in parts if isinstance(p, str) and p) or None

        description = raw.get("descriptionPlain")
        if not description:
            description = strip_html(raw.get("descriptionHtml"))

        department = (raw.get("department") or "").strip() or None
        team = (raw.get("team") or "").strip() or None
        if team and not department:
            department = team

        employment_type = (raw.get("employmentType") or "").strip() or None
        if employment_type:
            employment_type = employment_type.replace("FullTime", "Full-time").replace(
                "PartTime", "Part-time"
            )

        remote_type = detect_remote_type(location, description, raw.get("workplaceType"))

        posted_date: datetime | None = None
        for key in ("publishedAt", "updatedAt", "createdAt"):
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
            remote_type=remote_type,
            department=department,
            employment_type=employment_type,
            experience_min=exp_min,
            experience_max=exp_max,
            posted_date=posted_date,
            raw_payload=raw if isinstance(raw, dict) else {},
        )
