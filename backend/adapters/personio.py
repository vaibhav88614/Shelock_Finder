"""Personio ATS adapter.

Public XML feed, no auth required:
    GET https://<company>.jobs.personio.de/xml

Returns `<workzag-jobs><position>...</position>...</workzag-jobs>`.
Each `<position>` is a flat element with child tags:
    id, subcompany, office, department, recruitingCategory, name (=title),
    jobDescriptions (HTML), employmentType, seniority, schedule,
    yearsOfExperience, keywords, occupation, createdAt

`ats_identifier` is the Personio subdomain (e.g. "monday").
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import httpx
from dateutil import parser as dateparser
from loguru import logger

from ._experience import parse_experience
from ._text import detect_remote_type, strip_html
from .base import AdapterError, BaseAdapter, NormalizedJob, RawJob


def _child_text(el: ET.Element, tag: str) -> str | None:
    """Return concatenated text of the first child with `tag` (or any ns)."""
    for child in el:
        # Strip XML namespaces if present.
        local = child.tag.rsplit("}", 1)[-1]
        if local == tag:
            return "".join(child.itertext()).strip() or None
    return None


def _element_to_dict(el: ET.Element) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for child in el:
        local = child.tag.rsplit("}", 1)[-1]
        # `jobDescriptions` is a container with <jobDescription><name/><value/></jobDescription>
        if local == "jobDescriptions":
            parts: list[str] = []
            for jd in child:
                name = _child_text(jd, "name") or ""
                value = _child_text(jd, "value") or ""
                parts.append(f"## {name}\n{value}" if name else value)
            out["jobDescriptions"] = "\n\n".join(p for p in parts if p) or None
        else:
            text = "".join(child.itertext()).strip()
            out[local] = text or None
    return out


class PersonioAdapter(BaseAdapter):
    ats_type = "personio"

    async def fetch(self, company) -> list[RawJob]:  # noqa: ANN001
        sub = (company.ats_identifier or "").strip()
        if not sub:
            raise AdapterError(
                f"Personio adapter requires ats_identifier on company {company.name!r}"
            )
        url = f"https://{sub}.jobs.personio.de/xml"
        try:
            resp = await self.request("GET", url, headers={"Accept": "application/xml,text/xml"})
        except httpx.HTTPError as e:
            raise AdapterError(f"Personio fetch failed for {sub!r}: {e}") from e
        if resp.status_code == 404:
            raise AdapterError(f"Personio subdomain {sub!r} not found (404)")
        if resp.status_code >= 400:
            raise AdapterError(f"Personio {sub!r} HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as e:
            raise AdapterError(f"Personio {sub!r} returned invalid XML: {e}") from e

        positions: list[RawJob] = []
        for el in root.iter():
            local = el.tag.rsplit("}", 1)[-1]
            if local == "position":
                positions.append(_element_to_dict(el))
        logger.debug("Personio[{}]: {} jobs", sub, len(positions))
        return positions

    def normalize(self, raw: RawJob, company) -> NormalizedJob:  # noqa: ANN001
        external_id = raw.get("id") or None
        external_id = str(external_id) if external_id else None
        title = (raw.get("name") or "").strip()
        sub = (company.ats_identifier or "").strip()
        apply_url = (
            raw.get("url")
            or (f"https://{sub}.jobs.personio.de/job/{external_id}" if external_id else "")
        ).strip()

        location = (raw.get("office") or "").strip() or None
        department = (raw.get("department") or raw.get("recruitingCategory") or "").strip() or None
        employment_type = (raw.get("employmentType") or raw.get("schedule") or "").strip() or None

        description = strip_html(raw.get("jobDescriptions"))
        keywords = raw.get("keywords")
        if isinstance(keywords, str) and keywords:
            description = ((description or "") + "\n\nKeywords: " + keywords).strip()

        remote_type = detect_remote_type(location, description, raw.get("schedule"))

        posted_date: datetime | None = None
        v = raw.get("createdAt")
        if isinstance(v, str) and v:
            try:
                dt = dateparser.parse(v)
                posted_date = dt.replace(tzinfo=None) if dt.tzinfo else dt
            except (ValueError, TypeError):
                posted_date = None

        # Personio sometimes provides yearsOfExperience like "1-2", "5+", "lt-1".
        yoe = raw.get("yearsOfExperience")
        exp_min, exp_max = None, None
        if isinstance(yoe, str) and yoe.strip():
            # Append "years" so the generic parser (which requires that word) matches.
            exp_min, exp_max = parse_experience(f"{yoe.strip()} years")
        if exp_min is None and exp_max is None:
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
