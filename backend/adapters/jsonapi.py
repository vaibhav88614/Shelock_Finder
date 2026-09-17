"""Generic JSON-API adapter — for careers backed by a discoverable JSON endpoint.

Some employers run bespoke SPA career sites (Amazon, Dell, ...) whose jobs come
from a public JSON API rather than server-rendered HTML, so neither the
Greenhouse/Lever/... tier-1 adapters nor the HTML `custom`/`playwright` adapters
fit. This adapter reads a declarative config from `company.custom_selectors`
(JSON) and maps an arbitrary JSON response onto `NormalizedJob`.

`ats_type == "jsonapi"`. Config schema (all but api_url/jobs_path/fields.title
optional):

    {
      "api_url":   "https://www.amazon.jobs/en/search.json",   # REQUIRED
      "method":    "GET",                    # or "POST"
      "params":    {"sort": "recent"},       # query string (GET)
      "body":      {"limit": 20},            # JSON body (POST)
      "headers":   {"X-…": "…"},
      "impersonate": "chrome",               # use curl_cffi TLS impersonation to
                                             # bypass bot walls (Cloudflare/Akamai)
      "jobs_path": "jobs",                   # dot-path to the array; numeric
                                             # segments index lists ("items.0.requisitionList");
                                             # "$" means the response itself is the array
      "fields": {                            # NormalizedJob field -> source dot-path
        "external_id": "id_icims", "title": "title", "apply_url": "job_path",
        "location": "normalized_location", "posted_date": "posted_date",
        "department": "job_category", "employment_type": "…", "description": "…"
      },
      "url_base":     "https://www.amazon.jobs",   # prepend to a relative apply_url
      "url_template": "https://…/job/{Id}",        # OR build apply_url from raw {field}s
      "page_param":   "offset",              # query param bumped each page
      "page_start":   0,                     # first page value (default 0)
      "page_size":    100,                   # increment + page size
      "max_records":  1000                   # safety cap
    }
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import httpx
from dateutil import parser as dateparser
from loguru import logger

from ._experience import parse_experience
from ._text import as_text, detect_remote_type, strip_html
from .base import AdapterError, BaseAdapter, NormalizedJob, RawJob


_TEMPLATE_FIELD_RE = re.compile(r"\{([^{}]+)\}")


def _coerce_config(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise AdapterError(f"jsonapi custom_selectors is not valid JSON: {e}") from e
    raise AdapterError("JsonApiAdapter requires custom_selectors (JSON config) on the Company row")


def _dig(obj: Any, path: str | None) -> Any:
    """Navigate a dot-path, treating all-digit segments as list indices."""
    if not path:
        return None
    cur = obj
    for seg in path.split("."):
        if cur is None:
            return None
        if seg.isdigit():
            if isinstance(cur, (list, tuple)) and int(seg) < len(cur):
                cur = cur[int(seg)]
            else:
                return None
        elif isinstance(cur, dict):
            cur = cur.get(seg)
        else:
            return None
    return cur


class JsonApiAdapter(BaseAdapter):
    ats_type = "jsonapi"

    def _config(self, company) -> dict[str, Any]:  # noqa: ANN001
        cfg = _coerce_config(getattr(company, "custom_selectors", None))
        if not cfg.get("api_url"):
            raise AdapterError("jsonapi config missing 'api_url'")
        fields = cfg.get("fields")
        if not isinstance(fields, dict) or not fields.get("title"):
            raise AdapterError("jsonapi config missing fields.title")
        return cfg

    async def _request_json(self, cfg: dict[str, Any], params: dict[str, Any]) -> Any:
        method = (cfg.get("method") or "GET").upper()
        headers = {"Accept": "application/json", **(cfg.get("headers") or {})}
        body = cfg.get("body") if method == "POST" else None
        impersonate = cfg.get("impersonate")

        if impersonate:
            # curl_cffi mimics a real browser's TLS/JA3 fingerprint, which gets
            # past bot walls that reject the default httpx client.
            try:
                from curl_cffi.requests import AsyncSession  # type: ignore
            except ImportError as e:
                raise AdapterError(
                    "jsonapi impersonate set but curl_cffi is not installed "
                    "(pip install curl_cffi)."
                ) from e
            async with AsyncSession() as s:
                resp = await s.request(
                    method, cfg["api_url"], params=params, json=body,
                    headers=headers, impersonate=str(impersonate), timeout=30,
                )
                if resp.status_code >= 400:
                    raise AdapterError(f"jsonapi {cfg['api_url']} HTTP {resp.status_code}")
                try:
                    return resp.json()
                except Exception as e:  # noqa: BLE001
                    raise AdapterError(f"jsonapi {cfg['api_url']} non-JSON: {e}") from e

        try:
            resp = await self.request_with_retry(
                method, cfg["api_url"], params=params, json=body, headers=headers
            )
        except httpx.HTTPError as e:
            raise AdapterError(f"jsonapi fetch failed for {cfg['api_url']}: {e}") from e
        if resp.status_code >= 400:
            raise AdapterError(
                f"jsonapi {cfg['api_url']} HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as e:
            raise AdapterError(f"jsonapi {cfg['api_url']} non-JSON: {e}") from e

    async def fetch(self, company) -> list[RawJob]:  # noqa: ANN001
        cfg = self._config(company)
        jobs_path = cfg.get("jobs_path") or "jobs"
        page_param = cfg.get("page_param")
        page_size = int(cfg.get("page_size") or 100)
        max_records = int(cfg.get("max_records") or 1000)
        base_params = dict(cfg.get("params") or {})

        out: list[RawJob] = []
        offset = int(cfg.get("page_start") or 0)
        while True:
            params = dict(base_params)
            if page_param:
                params[page_param] = offset
            data = await self._request_json(cfg, params)
            page = data if jobs_path == "$" else _dig(data, jobs_path)
            if not isinstance(page, list):
                if offset == int(cfg.get("page_start") or 0):
                    raise AdapterError(
                        f"jsonapi {company.name!r}: jobs_path {jobs_path!r} did not resolve to a list"
                    )
                break
            out.extend(x for x in page if isinstance(x, dict))
            if not page_param or len(page) < page_size or len(out) >= max_records:
                break
            offset += page_size
        logger.debug("JsonApi[{}]: {} jobs", company.name, len(out))
        return out[:max_records]

    def _apply_url(self, cfg: dict[str, Any], raw: RawJob, fields: dict[str, Any]) -> str:
        template = cfg.get("url_template")
        if template:
            return _TEMPLATE_FIELD_RE.sub(lambda m: str(_dig(raw, m.group(1)) or ""), template)
        val = as_text(_dig(raw, fields.get("apply_url")))
        base = cfg.get("url_base")
        if val and base and not val.startswith(("http://", "https://")):
            return base.rstrip("/") + "/" + val.lstrip("/")
        return val

    def normalize(self, raw: RawJob, company) -> NormalizedJob:  # noqa: ANN001
        cfg = self._config(company)
        fields = cfg.get("fields") or {}

        title = as_text(_dig(raw, fields.get("title")))
        apply_url = self._apply_url(cfg, raw, fields)
        external_id = as_text(_dig(raw, fields.get("external_id"))) or None
        location = as_text(_dig(raw, fields.get("location"))) or None
        department = as_text(_dig(raw, fields.get("department"))) or None
        employment_type = as_text(_dig(raw, fields.get("employment_type"))) or None

        description = _dig(raw, fields.get("description"))
        description = strip_html(description) if isinstance(description, str) else None

        posted_date: datetime | None = None
        pd = _dig(raw, fields.get("posted_date"))
        if isinstance(pd, str) and pd.strip():
            try:
                dt = dateparser.parse(pd, fuzzy=True)
                posted_date = dt.replace(tzinfo=None) if dt and dt.tzinfo else dt
            except (ValueError, TypeError, OverflowError):
                posted_date = None

        remote_type = detect_remote_type(location, description, as_text(_dig(raw, fields.get("workplace"))))
        exp_min, exp_max = parse_experience(description) if description else (None, None)

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
            raw_payload=raw,
        )
