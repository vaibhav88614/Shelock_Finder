"""Workday ATS adapter.

Workday's careers pages are React shells fed by an internal JSON API at:
    POST https://<host>/wday/cxs/<tenant>/<site>/jobs
    body: {"appliedFacets": {}, "limit": 20, "offset": N, "searchText": ""}

Response:
    {"jobPostings": [{"title", "externalPath", "locationsText", "postedOn",
                      "bulletFields": ["JR-12345"], "startDate"?: "2026-04-12"}],
     "total": N}

A per-job description requires another POST to:
    /wday/cxs/<tenant>/<site>/job<externalPath>
which is currently skipped to keep the per-company HTTP budget within
Workday's tight 2-req/s ceiling. Title + bullet fields go into FTS.

`ats_identifier` packs three pieces separated by `|`:
    "<host>|<tenant>|<site>"
e.g. "nvidia.wd5.myworkdayjobs.com|nvidia|NVIDIAExternalCareerSite".
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import httpx
from dateutil import parser as dateparser
from loguru import logger

from ._experience import parse_experience
from ._text import detect_remote_type
from .base import AdapterError, BaseAdapter, NormalizedJob, RawJob


_REL_DAYS_RE = re.compile(r"(\d+)\+?\s*Days?\s*Ago", re.IGNORECASE)
_REL_MONTHS_RE = re.compile(r"(\d+)\+?\s*Months?\s*Ago", re.IGNORECASE)
_TODAY_RE = re.compile(r"\b(today|just posted|posted today)\b", re.IGNORECASE)
_YESTERDAY_RE = re.compile(r"\byesterday\b", re.IGNORECASE)


def _parse_workday_identifier(ats_identifier: str | None) -> tuple[str, str, str]:
    parts = (ats_identifier or "").split("|")
    if len(parts) != 3 or not all(p.strip() for p in parts):
        raise AdapterError(
            "Workday adapter expects ats_identifier='<host>|<tenant>|<site>' "
            f"got {ats_identifier!r}"
        )
    return parts[0].strip(), parts[1].strip(), parts[2].strip()


def _parse_relative_posted(s: str | None, now: datetime | None = None) -> datetime | None:
    if not s:
        return None
    base = now or datetime.utcnow()
    text = s.strip()
    if _TODAY_RE.search(text):
        return base
    if _YESTERDAY_RE.search(text):
        return base - timedelta(days=1)
    m = _REL_DAYS_RE.search(text)
    if m:
        return base - timedelta(days=int(m.group(1)))
    m = _REL_MONTHS_RE.search(text)
    if m:
        return base - timedelta(days=30 * int(m.group(1)))
    return None


class WorkdayAdapter(BaseAdapter):
    ats_type = "workday"
    PAGE_LIMIT = 20

    async def fetch(self, company) -> list[RawJob]:  # noqa: ANN001
        host, tenant, site = _parse_workday_identifier(company.ats_identifier)
        url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        # Many Workday tenants reject the bare API call with HTTP 422 unless the
        # request looks like it came from their own JS shell. Origin + Referer +
        # a browser-class UA satisfies the server-side CSRF/XHR check.
        site_root = f"https://{host}/en-US/{site}"
        req_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": f"https://{host}",
            "Referer": site_root,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        out: list[RawJob] = []
        offset = 0
        while True:
            payload = {
                "appliedFacets": {},
                "limit": self.PAGE_LIMIT,
                "offset": offset,
                "searchText": "",
            }
            try:
                resp = await self.client.post(url, json=payload, headers=req_headers)
            except httpx.HTTPError as e:
                raise AdapterError(f"Workday fetch failed for {tenant}/{site}: {e}") from e
            if resp.status_code == 404:
                raise AdapterError(f"Workday site {tenant}/{site} not found (404)")
            if resp.status_code >= 400:
                raise AdapterError(
                    f"Workday {tenant}/{site} HTTP {resp.status_code}: {resp.text[:200]}"
                )
            try:
                data = resp.json()
            except ValueError as e:
                raise AdapterError(f"Workday {tenant}/{site} non-JSON: {e}") from e
            page = data.get("jobPostings")
            if not isinstance(page, list):
                raise AdapterError(f"Workday {tenant}/{site} missing 'jobPostings' list")
            # Stamp host+site so normalize() can build absolute apply URLs without re-parsing.
            for entry in page:
                if isinstance(entry, dict):
                    entry["__host"] = host
                    entry["__site"] = site
            out.extend(page)
            total = int(data.get("total") or 0)
            offset += len(page)
            if not page or offset >= total or len(out) >= 5000:
                break
        logger.debug("Workday[{}/{}]: {} jobs", tenant, site, len(out))
        return out

    def normalize(self, raw: RawJob, company) -> NormalizedJob:  # noqa: ANN001
        host = raw.get("__host") or ""
        site = raw.get("__site") or ""
        bullets = raw.get("bulletFields") or []
        external_id = None
        if isinstance(bullets, list) and bullets:
            external_id = str(bullets[0]).strip() or None
        if not external_id:
            ext_path = raw.get("externalPath") or ""
            if ext_path:
                external_id = ext_path.rsplit("/", 1)[-1] or None

        title = (raw.get("title") or "").strip()
        ext_path = (raw.get("externalPath") or "").strip()
        # Workday's externalPath is usually `/job/<Location>/<slug>_R-12345`
        # (NO locale/site prefix). The user-facing URL needs `/en-US/<site>`
        # in front, otherwise the link lands on the generic careers home.
        if not ext_path:
            apply_url = ""
        elif "/en-" in ext_path[:8] or (site and f"/{site}/" in ext_path):
            # Already absolute-ish (some tenants return the full path).
            apply_url = f"https://{host}{ext_path}" if host else ext_path
        else:
            apply_url = (
                f"https://{host}/en-US/{site}{ext_path}" if host and site else
                (f"https://{host}{ext_path}" if host else ext_path)
            )

        location = (raw.get("locationsText") or "").strip() or None

        description_bits: list[str] = []
        if isinstance(bullets, list):
            description_bits.extend(str(b) for b in bullets if b)
        description = "\n".join(description_bits) or None

        posted_date: datetime | None = None
        sd = raw.get("startDate")
        if isinstance(sd, str) and sd:
            try:
                dt = dateparser.parse(sd)
                posted_date = dt.replace(tzinfo=None) if dt.tzinfo else dt
            except (ValueError, TypeError):
                posted_date = None
        if posted_date is None:
            posted_date = _parse_relative_posted(raw.get("postedOn"))

        remote_type = detect_remote_type(location, description)

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
            department=None,
            employment_type=None,
            experience_min=exp_min,
            experience_max=exp_max,
            posted_date=posted_date,
            raw_payload={k: v for k, v in raw.items() if k not in ("__host", "__site")},
        )
