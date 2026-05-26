"""Teamtailor ATS adapter.

Public JSON endpoint, no auth required:
    GET https://<subdomain>.teamtailor.com/jobs.json

Returns either a top-level list or `{jobs: [...]}`. Each entry typically has:
    id, title, body (HTML), pitch, careersite_job_url / url, published_at,
    department, location, locations, tags, remote_status, language

`ats_identifier` is the Teamtailor subdomain.
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


class TeamtailorAdapter(BaseAdapter):
    ats_type = "teamtailor"

    async def fetch(self, company) -> list[RawJob]:  # noqa: ANN001
        sub = (company.ats_identifier or "").strip()
        if not sub:
            raise AdapterError(
                f"Teamtailor adapter requires ats_identifier on company {company.name!r}"
            )
        url = f"https://{sub}.teamtailor.com/jobs.json"
        try:
            resp = await self.client.get(url)
        except httpx.HTTPError as e:
            raise AdapterError(f"Teamtailor fetch failed for {sub!r}: {e}") from e
        if resp.status_code == 404:
            raise AdapterError(f"Teamtailor subdomain {sub!r} not found (404)")
        if resp.status_code >= 400:
            raise AdapterError(f"Teamtailor {sub!r} HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as e:
            raise AdapterError(f"Teamtailor {sub!r} non-JSON: {e}") from e
        if isinstance(data, list):
            jobs = data
        elif isinstance(data, dict):
            jobs = data.get("jobs") or data.get("data") or []
        else:
            raise AdapterError(f"Teamtailor {sub!r} unexpected response type {type(data).__name__}")
        if not isinstance(jobs, list):
            raise AdapterError(f"Teamtailor {sub!r} missing jobs list")
        logger.debug("Teamtailor[{}]: {} jobs", sub, len(jobs))
        return jobs

    def normalize(self, raw: RawJob, company) -> NormalizedJob:  # noqa: ANN001
        external_id = raw.get("id")
        external_id = str(external_id) if external_id is not None else None
        title = (raw.get("title") or "").strip()
        apply_url = (
            raw.get("careersite_job_url")
            or raw.get("url")
            or raw.get("apply_url")
            or ""
        )
        apply_url = apply_url.strip() if isinstance(apply_url, str) else ""

        location: str | None = None
        loc = raw.get("location")
        if isinstance(loc, str) and loc.strip():
            location = loc.strip()
        elif isinstance(loc, dict):
            parts = [loc.get(k) for k in ("city", "region", "country", "name")]
            location = ", ".join(p for p in parts if isinstance(p, str) and p) or None
        if not location:
            locs = raw.get("locations")
            if isinstance(locs, list) and locs:
                first = locs[0]
                if isinstance(first, str):
                    location = first
                elif isinstance(first, dict):
                    parts = [first.get(k) for k in ("city", "region", "country", "name")]
                    location = ", ".join(p for p in parts if isinstance(p, str) and p) or None

        department = (raw.get("department") or "").strip() or None
        employment_type = (raw.get("employment_type") or raw.get("contract_type") or "").strip() or None

        desc_parts = [raw.get("pitch"), raw.get("body"), raw.get("description")]
        joined = "\n\n".join(p for p in desc_parts if isinstance(p, str) and p)
        description = strip_html(joined) if joined else None

        remote_type: str | None = None
        rs = raw.get("remote_status") or raw.get("remote")
        if isinstance(rs, str):
            rs_l = rs.lower()
            if rs_l in {"fully", "remote", "true", "always"}:
                remote_type = "remote"
            elif rs_l in {"hybrid", "temporary", "sometimes"}:
                remote_type = "hybrid"
            elif rs_l in {"none", "no", "false", "onsite"}:
                remote_type = "onsite"
        elif rs is True:
            remote_type = "remote"
        if remote_type is None:
            remote_type = detect_remote_type(location, description)

        posted_date: datetime | None = None
        for key in ("published_at", "created_at", "updated_at"):
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
