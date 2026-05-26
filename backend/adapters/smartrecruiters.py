"""SmartRecruiters ATS adapter.

Public REST endpoint, no auth required for posted jobs:
    https://api.smartrecruiters.com/v1/companies/<company>/postings?limit=100&offset=N

Returns `{content: [postings], totalFound, offset, limit}`.
A posting only carries shallow fields (id, name, location, releasedDate, ...);
the long-form description requires a per-id call to `/postings/<id>` which we
skip here to stay within the per-company rate budget. Title + custom-field
text is still indexed by FTS5.

`ats_identifier` is the SmartRecruiters company token (e.g. "Box").
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


class SmartRecruitersAdapter(BaseAdapter):
    ats_type = "smartrecruiters"
    BASE_URL = "https://api.smartrecruiters.com/v1/companies"
    PAGE_LIMIT = 100

    async def fetch(self, company) -> list[RawJob]:  # noqa: ANN001
        token = (company.ats_identifier or "").strip()
        if not token:
            raise AdapterError(
                f"SmartRecruiters adapter requires ats_identifier on company {company.name!r}"
            )
        out: list[RawJob] = []
        offset = 0
        while True:
            url = f"{self.BASE_URL}/{token}/postings?limit={self.PAGE_LIMIT}&offset={offset}"
            try:
                resp = await self.client.get(url)
            except httpx.HTTPError as e:
                raise AdapterError(f"SmartRecruiters fetch failed for {token!r}: {e}") from e
            if resp.status_code == 404:
                raise AdapterError(f"SmartRecruiters company {token!r} not found (404)")
            if resp.status_code >= 400:
                raise AdapterError(
                    f"SmartRecruiters {token!r} HTTP {resp.status_code}: {resp.text[:200]}"
                )
            try:
                data = resp.json()
            except ValueError as e:
                raise AdapterError(f"SmartRecruiters {token!r} non-JSON: {e}") from e
            page = data.get("content")
            if not isinstance(page, list):
                raise AdapterError(f"SmartRecruiters {token!r} missing 'content' list")
            out.extend(page)
            total = int(data.get("totalFound") or 0)
            offset += len(page)
            if not page or offset >= total or len(out) >= 5000:
                break
        logger.debug("SmartRecruiters[{}]: {} jobs", token, len(out))
        return out

    def normalize(self, raw: RawJob, company) -> NormalizedJob:  # noqa: ANN001
        external_id = (raw.get("id") or raw.get("uuid") or "")
        external_id = str(external_id) if external_id else None
        title = (raw.get("name") or "").strip()

        # Build a stable apply URL from the company + posting id.
        token = (company.ats_identifier or "").strip()
        apply_url = raw.get("ref") or raw.get("applyUrl") or ""
        if not apply_url and external_id:
            apply_url = f"https://jobs.smartrecruiters.com/{token}/{external_id}"
        apply_url = apply_url.strip() if isinstance(apply_url, str) else ""

        loc = raw.get("location") or {}
        location = None
        if isinstance(loc, dict):
            parts = [loc.get(k) for k in ("city", "region", "country")]
            location = ", ".join(p for p in parts if isinstance(p, str) and p) or None
            if loc.get("remote") is True and not location:
                location = "Remote"

        department = None
        dept = raw.get("department") or {}
        if isinstance(dept, dict):
            department = (dept.get("label") or dept.get("title") or "").strip() or None
        function = raw.get("function") or {}
        if not department and isinstance(function, dict):
            department = (function.get("label") or "").strip() or None

        employment_type = None
        emp = raw.get("typeOfEmployment") or {}
        if isinstance(emp, dict):
            employment_type = (emp.get("label") or "").strip() or None

        # Description fields the list endpoint may carry:
        description_parts: list[str] = []
        for fld in ("jobAd", "customField"):
            v = raw.get(fld)
            if isinstance(v, dict):
                for section in v.get("sections", {}).values() if isinstance(v.get("sections"), dict) else []:
                    if isinstance(section, dict):
                        text = section.get("text")
                        if isinstance(text, str):
                            description_parts.append(text)
        description = strip_html("\n".join(description_parts)) if description_parts else None

        remote_type = detect_remote_type(location, description)
        if remote_type is None and isinstance(loc, dict) and loc.get("remote") is True:
            remote_type = "remote"

        posted_date: datetime | None = None
        for key in ("releasedDate", "createdOn", "updatedOn"):
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
