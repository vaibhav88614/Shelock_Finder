"""Auto-heal stale seed identifiers in seeds/companies.json.

Many seeded boards 404 because the company moved ATS or renamed its board.
This maintenance tool live-probes each company and, for the failing ones, tries
alternative (ATS family, identifier) candidates against the real adapters. Any
candidate that returns >=1 live job is applied back to the seed file, with the
`careers_url` rewritten to the canonical form so `detect_ats()` still agrees.

Only live-confirmed changes are written. Review the result with `git diff
seeds/companies.json`.

    python scripts/heal_seeds.py            # heal all
    python scripts/heal_seeds.py --dry-run  # report only, write nothing
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import httpx

from backend.adapters import get_adapter_cls
from backend.config import settings

SEEDS = Path("seeds/companies.json")

# Families we can guess an identifier for from the company name/slug. Workday
# needs a 3-part host|tenant|site id that can't be guessed; custom/playwright
# need selectors. Personio is excluded as a *candidate* family (aggressive 429s
# on blind probes) but existing personio seeds still benefit from the current
# probe + retry.
CANDIDATE_FAMILIES = [
    "ashby",
    "greenhouse",
    "lever",
    "workable",
    "smartrecruiters",
    "recruitee",
    "teamtailor",
]

PROBE_TIMEOUT_S = 12.0
CONCURRENCY = 6


def canonical_url(family: str, ident: str) -> str:
    return {
        "greenhouse": f"https://boards.greenhouse.io/{ident}",
        "lever": f"https://jobs.lever.co/{ident}",
        "ashby": f"https://jobs.ashbyhq.com/{ident}",
        "smartrecruiters": f"https://jobs.smartrecruiters.com/{ident}",
        "workable": f"https://apply.workable.com/{ident}",
        "recruitee": f"https://{ident}.recruitee.com",
        "personio": f"https://{ident}.jobs.personio.de",
        "teamtailor": f"https://{ident}.teamtailor.com",
    }[family]


def identifier_candidates(name: str, current: str | None) -> list[str]:
    """Ordered, de-duplicated identifier guesses derived from the company."""
    lower = name.lower()
    alnum = re.sub(r"[^a-z0-9]", "", lower)
    hyphen = re.sub(r"[^a-z0-9]+", "-", lower).strip("-")
    out: list[str] = []
    for cand in (current, alnum, hyphen):
        if cand and cand not in out:
            out.append(cand)
    return out


def _fake_company(family: str, ident: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=0, name=name, ats_type=family, ats_identifier=ident,
        careers_url=canonical_url(family, ident), custom_selectors=None,
    )


async def _job_count(client, family: str, ident: str, name: str) -> int | None:
    """Return live job count for (family, ident), or None on any failure."""
    try:
        cls = get_adapter_cls(family)
    except Exception:  # noqa: BLE001
        return None
    adapter = cls(client=client)
    try:
        raws = await asyncio.wait_for(
            adapter.fetch(_fake_company(family, ident, name)), PROBE_TIMEOUT_S
        )
        return len(raws)
    except Exception:  # noqa: BLE001
        return None


async def heal_company(client, sem, row: dict) -> dict:
    name = row["name"]
    declared = row.get("ats_type", "custom")
    current = row.get("ats_identifier")

    async with sem:
        # 1. Does the current config still work (retry may recover 429s)?
        if declared in CANDIDATE_FAMILIES or declared in ("personio", "workday"):
            n = await _job_count(client, declared, current, name) if current else None
            if n and n > 0:
                return {"name": name, "status": "ok", "jobs": n}

        # 2. Only attempt to re-point families we can guess an id for.
        if declared in ("workday", "custom", "playwright"):
            return {"name": name, "status": "unfixable", "reason": declared}

        ids = identifier_candidates(name, current)
        for family in CANDIDATE_FAMILIES:
            for ident in ids:
                if family == declared and ident == current:
                    continue  # already known-bad
                n = await _job_count(client, family, ident, name)
                if n and n > 0:
                    return {
                        "name": name, "status": "fixed", "jobs": n,
                        "old": (declared, current), "new": (family, ident),
                    }
        return {"name": name, "status": "broken"}


async def _verify_fix(client, res: dict) -> dict:
    """Sequentially re-confirm a proposed fix to avoid concurrency false-positives.

    Keep the fix only if the OLD config truly fails/returns 0 AND the NEW config
    returns >=1 job. If the OLD config actually still works, drop the fix.
    """
    name = res["name"]
    old_family, old_id = res["old"]
    if old_id:
        old_n = await _job_count(client, old_family, old_id, name)
        if old_n and old_n > 0:
            return {"name": name, "status": "ok", "jobs": old_n}
    new_family, new_id = res["new"]
    new_n = await _job_count(client, new_family, new_id, name)
    if new_n and new_n > 0:
        return {**res, "jobs": new_n}
    return {"name": name, "status": "broken"}


async def main(dry_run: bool) -> None:
    rows = json.loads(SEEDS.read_text(encoding="utf-8"))
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent},
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        results = await asyncio.gather(*(heal_company(client, sem, r) for r in rows))

        # Sequential verification pass for proposed fixes (concurrency 1) so a
        # transiently throttled current-config probe can't cause a wrong re-point.
        verified: list[dict] = []
        for r in results:
            if r["status"] == "fixed":
                verified.append(await _verify_fix(client, r))
            else:
                verified.append(r)
        results = verified

    by_name = {r["name"]: r for r in results}
    fixed = [r for r in results if r["status"] == "fixed"]
    ok = [r for r in results if r["status"] == "ok"]
    broken = [r for r in results if r["status"] == "broken"]
    unfixable = [r for r in results if r["status"] == "unfixable"]

    # Apply fixes to the seed rows (in place, preserving key order/shape).
    if not dry_run:
        for row in rows:
            res = by_name.get(row["name"])
            if res and res["status"] == "fixed":
                family, ident = res["new"]
                row["ats_type"] = family
                row["ats_identifier"] = ident
                row["careers_url"] = canonical_url(family, ident)
        SEEDS.write_text(
            json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    print("=" * 64)
    print(f"Seeds: {len(rows)}   already-ok: {len(ok)}   FIXED: {len(fixed)}   "
          f"still-broken: {len(broken)}   unfixable(workday/custom): {len(unfixable)}")
    print("=" * 64)
    print(f"FIXED ({len(fixed)}):")
    for r in sorted(fixed, key=lambda x: x["name"]):
        o = f"{r['old'][0]}:{r['old'][1]}"
        n = f"{r['new'][0]}:{r['new'][1]}"
        print(f"  {r['name']:<22} {o:<28} -> {n:<28} ({r['jobs']} jobs)")
    print("=" * 64)
    print(f"STILL BROKEN ({len(broken)}):")
    for r in sorted(broken, key=lambda x: x["name"]):
        print(f"  {r['name']}")
    if dry_run:
        print("\n(dry-run: seeds/companies.json NOT modified)")
    else:
        print(f"\nWrote {len(fixed)} fixes to {SEEDS}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()
    asyncio.run(main(args.dry_run))
