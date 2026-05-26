"""Seed loader (phase 1 stub).

Phase 7 will populate `seeds/companies.json` with all 200 entries. For now
this loads whatever is in that file (empty list is OK) and is idempotent
on `name`.
"""
from __future__ import annotations

import json
from pathlib import Path

from loguru import logger
from sqlalchemy import select

from .config import settings
from .db import session_scope
from .migrations import upgrade_to_head
from .models import Company


def _load_seed_file() -> list[dict]:
    path: Path = settings.seeds_dir / "companies.json"
    if not path.exists():
        logger.warning("Seed file {} does not exist yet; nothing to load.", path)
        return []
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"Seed file {path} must contain a JSON array")
    return data


def run_seed() -> int:
    """Load (or upsert) all seed companies. Returns count inserted."""
    upgrade_to_head()
    rows = _load_seed_file()
    inserted = 0
    with session_scope() as s:
        for row in rows:
            name = row["name"].strip()
            existing = s.scalar(select(Company).where(Company.name == name))
            if existing is not None:
                # Update mutable fields only; don't touch counters.
                existing.careers_url = row["careers_url"]
                existing.ats_type = row.get("ats_type", "custom")
                existing.ats_identifier = row.get("ats_identifier")
                existing.custom_selectors = (
                    json.dumps(row["custom_selectors"]) if row.get("custom_selectors") else None
                )
                if "active" in row:
                    existing.active = bool(row["active"])
                continue
            s.add(
                Company(
                    name=name,
                    careers_url=row["careers_url"],
                    ats_type=row.get("ats_type", "custom"),
                    ats_identifier=row.get("ats_identifier"),
                    custom_selectors=(
                        json.dumps(row["custom_selectors"])
                        if row.get("custom_selectors")
                        else None
                    ),
                    active=bool(row.get("active", True)),
                )
            )
            inserted += 1
    logger.info("Seed complete: {} new companies inserted ({} total in file).", inserted, len(rows))
    return inserted


if __name__ == "__main__":
    run_seed()
