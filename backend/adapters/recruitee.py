"""Recruitee ATS adapter.

Public REST endpoint, no auth required:
    GET https://<company>.recruitee.com/api/offers/

Returns `{offers: [{id, slug, title, location, city, country, careers_url,
careers_apply_url, description, requirements, department, employment_type_code,
remote, published_at, ...}], count: N}`.

`ats_identifier` is the Recruitee subdomain.
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


class RecruiteeAdapter(BaseAdapter):
    ats_type = "recruitee"

    async def fetch(self, company) -> list[RawJob]:  # noqa: ANN001
        sub = (company.ats_identifier or "").strip()
        if not sub:
            raise AdapterError(
                f"Recruitee adapter requires ats_identifier on company {company.name!r}"
            )
        url = f"https://{sub}.recruitee.com/api/offers/"
        try:
            resp = await self.client.get(url)
        except httpx.HTTPError as e:
            raise AdapterError(f"Recruitee fetch failed for {sub!r}: {e}") from e
        if resp.status_code == 404:
            raise AdapterError(f"Recruitee subdomain {sub!r} not found (404)")
        if resp.status_code >= 400:
            raise AdapterError(f"Recruitee {sub!r} HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as e:
            raise AdapterError(f"Recruitee {sub!r} non-JSON: {e}") from e
        offers = data.get("offers")
        if not isinstance(offers, list):
            raise AdapterError(f"Recruitee {sub!r} response missing 'offers' list")
        logger.debug("Recruitee[{}]: {} jobs", sub, len(offers))
        return offers

    def normalize(self, raw: RawJob, company) -> NormalizedJob:  # noqa: ANN001
        external_id = raw.get("id")
        external_id = str(external_id) if external_id is not None else None
        title = (raw.get("title") or "").strip()
        apply_url = (
            raw.get("careers_apply_url")
            or raw.get("careers_url")
            or ""
        )
        apply_url = apply_url.strip() if isinstance(apply_url, str) else ""

        loc_parts = [raw.get("city"), raw.get("country")]
        location = ", ".join(p for p in loc_parts if isinstance(p, str) and p) or None
        if not location:
            location = (raw.get("location") or "").strip() or None

        department = (raw.get("department") or "").strip() or None
        employment_type = (raw.get("employment_type_code") or raw.get("category_code") or "").strip() or None

        desc_html = "\n\n".join(
            v for v in (raw.get("description"), raw.get("requirements")) if isinstance(v, str)
        )
        description = strip_html(desc_html) if desc_html else None

        remote_type = None
        if raw.get("remote") is True:
            remote_type = "remote"
        elif isinstance(raw.get("remote"), str) and raw["remote"].lower() in {"remote", "hybrid", "onsite"}:
            remote_type = raw["remote"].lower()
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
