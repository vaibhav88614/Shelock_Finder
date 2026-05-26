"""Playwright HTML adapter — for sites whose careers pages need JS to render.

Renders the index page in headless Chromium, dumps the full DOM, then reuses
the BeautifulSoup selector engine from `_html_extract`. Detail pages are also
rendered if `detail_description` is set in `custom_selectors`.

`ats_type == "playwright"`. The Playwright Python package is imported lazily
so the rest of the project doesn't crash if it isn't installed; the scrape
orchestrator skips this adapter when `--no-playwright` is passed.

Selector spec is identical to CustomAdapter (see `_html_extract`), with one
extra optional key:

    "wait_for": ".job-row"   # CSS selector to wait for before grabbing HTML
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from dateutil import parser as dateparser
from loguru import logger

from ._experience import parse_experience
from ._html_extract import (
    extract_description_from_detail,
    extract_rows,
    validate_selectors,
)
from ._text import detect_remote_type, strip_html
from ..config import settings
from .base import AdapterError, BaseAdapter, NormalizedJob, RawJob


DETAIL_CONCURRENCY = 3
PAGE_TIMEOUT_MS = 30_000


def _coerce_selectors(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise AdapterError(f"custom_selectors is not valid JSON: {e}") from e
    raise AdapterError("PlaywrightAdapter requires custom_selectors on the Company row")


async def _load_playwright():
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except ImportError as e:
        raise AdapterError(
            "playwright is not installed. Run `pip install playwright && playwright install chromium`."
        ) from e
    return async_playwright


class PlaywrightAdapter(BaseAdapter):
    ats_type = "playwright"

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
                f"PlaywrightAdapter: no list_url or careers_url for company {company.name!r}"
            )
        return url

    async def fetch(self, company) -> list[RawJob]:  # noqa: ANN001
        spec = self._spec(company)
        list_url = self._list_url(company, spec)
        wait_for = spec.get("wait_for") or spec["list_item"]
        detail_sel = spec.get("detail_description")

        async_playwright = await _load_playwright()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=settings.user_agent)
                page = await context.new_page()
                page.set_default_timeout(PAGE_TIMEOUT_MS)
                try:
                    await page.goto(list_url, wait_until="domcontentloaded")
                    try:
                        await page.wait_for_selector(wait_for, timeout=PAGE_TIMEOUT_MS)
                    except Exception:  # noqa: BLE001
                        logger.warning("Playwright[{}]: wait_for {!r} timed out", company.name, wait_for)
                    html = await page.content()
                except Exception as e:  # noqa: BLE001
                    raise AdapterError(f"Playwright navigation failed for {list_url}: {e}") from e

                rows = extract_rows(html, spec, base_url=list_url)
                logger.debug("Playwright[{}]: {} rows from index", company.name, len(rows))

                if detail_sel:
                    await self._enrich_with_details(context, rows, detail_sel)
                return rows
            finally:
                await browser.close()

    async def _enrich_with_details(self, context, rows: list[dict[str, Any]], detail_sel: str) -> None:
        sem = asyncio.Semaphore(DETAIL_CONCURRENCY)

        async def _one(row: dict[str, Any]) -> None:
            url = row.get("detail_link") or row.get("apply_url")
            if not url:
                return
            async with sem:
                page = await context.new_page()
                page.set_default_timeout(PAGE_TIMEOUT_MS)
                try:
                    await page.goto(url, wait_until="domcontentloaded")
                    html = await page.content()
                    row["description"] = (
                        extract_description_from_detail(html, detail_sel) or row.get("description")
                    )
                except Exception as e:  # noqa: BLE001
                    logger.debug("Playwright detail fetch failed for {}: {}", url, e)
                finally:
                    await page.close()

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
            external_id=None,
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
