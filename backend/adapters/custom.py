"""Custom HTML adapter — BeautifulSoup-based scraping for sites without ATS APIs.

Reads `company.custom_selectors` (JSON) to learn:
  * which CSS selector identifies each job row on the index page
  * how to pluck title / apply URL / location / etc. out of each row
  * optionally, a per-row detail page to fetch for the full description

If the index page is JavaScript-rendered (no jobs in the raw HTML), use
`PlaywrightAdapter` instead.

`ats_type == "custom"`. `company.ats_identifier` is unused; the page URL is
taken from `custom_selectors.list_url` (preferred) or `company.careers_url`.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import httpx
from dateutil import parser as dateparser
from loguru import logger

from ._experience import parse_experience
from ._html_extract import (
    extract_description_from_detail,
    extract_rows,
    validate_selectors,
)
from ._text import detect_remote_type, strip_html
from .base import AdapterError, BaseAdapter, NormalizedJob, RawJob


DETAIL_CONCURRENCY = 5
DETAIL_TIMEOUT_S = 20.0


def _coerce_selectors(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise AdapterError(f"custom_selectors is not valid JSON: {e}") from e
    raise AdapterError("CustomAdapter requires custom_selectors on the Company row")


class CustomAdapter(BaseAdapter):
    ats_type = "custom"

    def _spec(self, company) -> dict[str, Any]:  # noqa: ANN001
        spec = _coerce_selectors(getattr(company, "custom_selectors", None))
        try:
            return validate_selectors(spec)
        except ValueError as e:
            raise AdapterError(str(e)) from e

    def _list_url(self, company, spec: dict[str, Any]) -> str:  # noqa: ANN001
        url = spec.get("list_url") or company.careers_url
        if not url:
            raise AdapterError(
                f"CustomAdapter: no list_url or careers_url for company {company.name!r}"
            )
        return url

    async def _get(self, url: str) -> str:
        try:
            resp = await self.client.get(
                url, headers={"Accept": "text/html,application/xhtml+xml"}
            )
        except httpx.HTTPError as e:
            raise AdapterError(f"Custom GET failed for {url}: {e}") from e
        if resp.status_code >= 400:
            raise AdapterError(f"Custom GET {url} HTTP {resp.status_code}")
        return resp.text

    async def fetch(self, company) -> list[RawJob]:  # noqa: ANN001
        spec = self._spec(company)
        list_url = self._list_url(company, spec)
        html = await self._get(list_url)
        rows = extract_rows(html, spec, base_url=list_url)
        logger.debug("Custom[{}]: {} rows from index", company.name, len(rows))

        detail_sel = spec.get("detail_description")
        if detail_sel:
            await self._enrich_with_details(rows, detail_sel)

        # Stash a hint so normalize() doesn't need company again.
        return rows

    async def _enrich_with_details(self, rows: list[dict[str, Any]], detail_sel: str) -> None:
        sem = asyncio.Semaphore(DETAIL_CONCURRENCY)

        async def _one(row: dict[str, Any]) -> None:
            url = row.get("detail_link") or row.get("apply_url")
            if not url:
                return
            try:
                async with sem:
                    html = await asyncio.wait_for(self._get(url), DETAIL_TIMEOUT_S)
                row["description"] = extract_description_from_detail(html, detail_sel) or row.get("description")
            except (asyncio.TimeoutError, AdapterError) as e:
                logger.debug("detail fetch failed for {}: {}", url, e)

        await asyncio.gather(*(_one(r) for r in rows))

    def normalize(self, raw: RawJob, company) -> NormalizedJob:  # noqa: ANN001
        title = (raw.get("title") or "").strip()
        apply_url = (raw.get("apply_url") or "").strip()
        location = raw.get("location") or None
        description = strip_html(raw.get("description")) if raw.get("description") else None

        posted_date: datetime | None = None
        pd_text = raw.get("posted_date")
        if isinstance(pd_text, str) and pd_text.strip():
            try:
                dt = dateparser.parse(pd_text, fuzzy=True)
                posted_date = dt.replace(tzinfo=None) if dt.tzinfo else dt
            except (ValueError, TypeError, OverflowError):
                posted_date = None

        remote_type = detect_remote_type(location, description)
        exp_min, exp_max = parse_experience(
            " ".join(filter(None, [title, description or ""]))[:5000]
        )

        return NormalizedJob(
            external_id=None,  # custom sites rarely expose a stable id; fallback fingerprint covers us
            title=title,
            apply_url=apply_url,
            description=description,
            location=location,
            remote_type=remote_type,
            department=raw.get("department") or None,
            employment_type=raw.get("employment_type") or None,
            experience_min=exp_min,
            experience_max=exp_max,
            posted_date=posted_date,
            raw_payload=raw if isinstance(raw, dict) else {},
        )
