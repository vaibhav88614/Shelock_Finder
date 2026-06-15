"""Workable ATS adapter.

Public POST endpoint, no auth required:
    POST https://apply.workable.com/api/v3/accounts/<subdomain>/jobs
    body: {"query": ""}             # newer accounts REJECT limit/offset with HTTP 400

Returns `{results: [...], total: N, nextPage?: "<token>"}`.

Each result entry contains:
    id, title, shortcode, code, full_title, location: {city, country, region, ...},
    locations: [...], department, function, employment_type, telecommuting (bool),
    description (HTML), requirements (HTML), benefits (HTML), published_on, ...

`ats_identifier` is the Workable account subdomain (e.g. "lyft").
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


class WorkableAdapter(BaseAdapter):
    ats_type = "workable"
    BASE_URL = "https://apply.workable.com/api/v3/accounts"
    MAX_PAGES = 50  # safety cap (~5000 jobs at typical page size)

    async def fetch(self, company) -> list[RawJob]:  # noqa: ANN001
        sub = (company.ats_identifier or "").strip()
        if not sub:
            raise AdapterError(
                f"Workable adapter requires ats_identifier on company {company.name!r}"
            )
        url = f"{self.BASE_URL}/{sub}/jobs"
        out: list[RawJob] = []
        body: dict[str, Any] = {"query": ""}
        for _ in range(self.MAX_PAGES):
            try:
                resp = await self.client.post(url, json=body)
            except httpx.HTTPError as e:
                raise AdapterError(f"Workable fetch failed for {sub!r}: {e}") from e
            if resp.status_code == 404:
                raise AdapterError(f"Workable account {sub!r} not found (404)")
            if resp.status_code >= 400:
                raise AdapterError(f"Workable {sub!r} HTTP {resp.status_code}: {resp.text[:200]}")
            try:
                data = resp.json()
            except ValueError as e:
                raise AdapterError(f"Workable {sub!r} non-JSON: {e}") from e
            page = data.get("results") or data.get("jobs") or []
            if not isinstance(page, list):
                raise AdapterError(f"Workable {sub!r} missing 'results' list")
            out.extend(page)
            if len(out) >= 5000:
                break
            # Workable's cursor pagination: response carries nextPage when more rows exist.
            token = data.get("nextPage") or data.get("next_page")
            if not token:
                break
            body = {"query": "", "token": str(token)}
        logger.debug("Workable[{}]: {} jobs", sub, len(out))
        return out

    def normalize(self, raw: RawJob, company) -> NormalizedJob:  # noqa: ANN001
        external_id = raw.get("shortcode") or raw.get("id") or raw.get("code")
        external_id = str(external_id) if external_id else None
        title = (raw.get("title") or raw.get("full_title") or "").strip()

        sub = (company.ats_identifier or "").strip()
        apply_url = (
            raw.get("url")
            or raw.get("application_url")
            or (f"https://apply.workable.com/{sub}/j/{external_id}" if external_id else "")
        )
        apply_url = apply_url.strip() if isinstance(apply_url, str) else ""

        loc = raw.get("location") or {}
        location = None
        if isinstance(loc, dict):
            parts = [loc.get(k) for k in ("city", "region", "country")]
            location = ", ".join(p for p in parts if isinstance(p, str) and p) or None
        if not location and isinstance(raw.get("locations"), list) and raw["locations"]:
            first = raw["locations"][0]
            if isinstance(first, dict):
                parts = [first.get(k) for k in ("city", "region", "country")]
                location = ", ".join(p for p in parts if isinstance(p, str) and p) or None

        department = (raw.get("department") or raw.get("function") or "").strip() or None
        employment_type = (raw.get("employment_type") or "").strip() or None

        desc_parts: list[str | None] = [
            raw.get("description"),
            raw.get("requirements"),
            raw.get("benefits"),
        ]
        joined = "\n\n".join(p for p in desc_parts if isinstance(p, str) and p)
        description = strip_html(joined) if joined else None

        remote_type = None
        if raw.get("telecommuting") is True or raw.get("remote") is True:
            remote_type = "remote"
        if remote_type is None:
            remote_type = detect_remote_type(location, description)

        posted_date: datetime | None = None
        for key in ("published_on", "created_at", "updated_at"):
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
