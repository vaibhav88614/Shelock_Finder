"""Add a single company by URL, auto-detecting its ATS when possible.

Phase 6 wires `detect_ats()` into this entrypoint:

  * Recognised URL → `ats_type` + `ats_identifier` are populated automatically.
  * Unknown URL    → stored as `ats_type="custom"`, leaving the user to fill
                     in `custom_selectors` later via the UI.

CLI flags override detection so power users can force a specific ATS.
"""
from __future__ import annotations

from urllib.parse import urlparse

from loguru import logger
from sqlalchemy import select

from .db import session_scope
from .detect import detect_ats
from .migrations import upgrade_to_head
from .models import Company


def add_company(
    url: str,
    name: str | None = None,
    ats: str | None = None,
    identifier: str | None = None,
) -> int:
    upgrade_to_head()
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL: {url!r}")

    detected_type, detected_id = detect_ats(url)
    final_type = (ats or detected_type or "custom").strip().lower()
    final_identifier = identifier or detected_id

    inferred_name = name or parsed.netloc.replace("www.", "").split(".")[0].title()
    with session_scope() as s:
        existing = s.scalar(select(Company).where(Company.name == inferred_name))
        if existing is not None:
            logger.info("Company {!r} already exists (id={}).", inferred_name, existing.id)
            return existing.id
        company = Company(
            name=inferred_name,
            careers_url=url,
            ats_type=final_type,
            ats_identifier=final_identifier,
            active=True,
        )
        s.add(company)
        s.flush()
        if detected_type:
            logger.info(
                "Added company {!r} (id={}) — detected ats_type={!r} identifier={!r}.",
                inferred_name, company.id, final_type, final_identifier,
            )
        else:
            logger.info(
                "Added company {!r} (id={}) — ATS not auto-detected, stored as 'custom'.",
                inferred_name, company.id,
            )
        return company.id
