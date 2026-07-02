"""Auto-heal stale seed identifiers in seeds/companies.json.

Many seeded boards 404 because the company moved ATS or renamed its board.
This maintenance tool live-probes each company and, for the failing ones, tries
alternative (ATS family, identifier) candidates against the real adapters. A
candidate that returns >=1 live job is applied back to the seed file **only
after** two independent safety checks pass:

  1. Sequential re-verification (avoids concurrency false-positives): the OLD
     config must truly fail AND the NEW candidate must return jobs.
  2. Name-vs-content guard (avoids wrong-company slug collisions): the seed's
     company name must be corroborated by the board's own employer/company name
     where the ATS exposes it. Generic names with no distinctive token, or
     candidates whose employer name doesn't overlap, are NOT auto-applied —
     they're reported as "needs-review" for a human to confirm.

`careers_url` is rewritten to the canonical form so `detect_ats()` still agrees.
An audit trail is written to `data/heal_report.csv`.

    python run.py heal-seeds                 # heal all (writes seeds + report)
    python run.py heal-seeds --dry-run       # report only, write nothing
    python run.py heal-seeds --min-ok 180    # exit non-zero if < 180 end up OK
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from loguru import logger

from backend.adapters import get_adapter_cls
from backend.config import settings

SEEDS = settings.seeds_dir / "companies.json"
REPORT_CSV = settings.data_dir / "heal_report.csv"

# Families we can guess an identifier for from the company name/slug. Workday
# is handled by a dedicated candidate generator (below). custom/playwright need
# selectors. Personio is excluded as a *candidate* family (aggressive 429s on
# blind probes); existing personio seeds still benefit from probe + retry.
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

# Tokens that don't distinguish one employer from another. A company name made
# up only of these is treated as "weak" and never auto-applied.
GENERIC_TOKENS = frozenset({
    "inc", "incorporated", "corp", "corporation", "llc", "ltd", "limited",
    "labs", "lab", "ai", "io", "hq", "the", "technologies", "technology",
    "group", "co", "com", "holdings", "global", "app", "apps", "software",
    "systems", "solutions", "digital", "studio", "studios", "team", "get",
    "try", "use", "join", "hello", "work", "works", "jobs", "careers", "com",
})


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------


def canonical_url(family: str, ident: str) -> str:
    if family == "workday":
        host, _tenant, site = ident.split("|")
        return f"https://{host}/en-US/{site}"
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


def distinctive_tokens(name: str) -> set[str]:
    """Name tokens that meaningfully identify the employer (len>=4, non-generic)."""
    toks = re.split(r"[^a-z0-9]+", name.lower())
    return {t for t in toks if len(t) >= 4 and t not in GENERIC_TOKENS}


def name_verdict(name: str, employer_text: str) -> str:
    """Decide whether a healed candidate really belongs to `name`.

    Returns one of:
      "weak"          — name has no distinctive token; can't safely auto-apply.
      "match"         — a distinctive name token appears in the employer text.
      "mismatch"      — employer text known but shares no distinctive token.
      "unverified"    — no employer signal available; distinctive name, accept.
    """
    dts = distinctive_tokens(name)
    if not dts:
        return "weak"
    text = (employer_text or "").lower()
    if not text.strip():
        return "unverified"
    return "match" if any(t in text for t in dts) else "mismatch"


def workday_candidates(current: str | None) -> list[str]:
    """Alternative Workday 'host|tenant|site' identifiers to try.

    Keeps tenant+site, varies the wd data-center pod (wd1..wd5) since tenants
    are periodically migrated across pods. Only meaningful when the current id
    already parses into three parts.
    """
    if not current or current.count("|") != 2:
        return []
    host, tenant, site = current.split("|")
    m = re.match(r"^(?P<t>[a-z0-9-]+)\.wd(?P<n>\d+)\.myworkdayjobs\.com$", host, re.IGNORECASE)
    out: list[str] = []
    if m:
        for n in range(1, 6):
            alt_host = f"{m.group('t')}.wd{n}.myworkdayjobs.com"
            cand = f"{alt_host}|{tenant}|{site}"
            if cand != current and cand not in out:
                out.append(cand)
    return out


# ---------------------------------------------------------------------------
# Live probing
# ---------------------------------------------------------------------------


def _fake_company(family: str, ident: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=0, name=name, ats_type=family, ats_identifier=ident,
        careers_url=canonical_url(family, ident), custom_selectors=None,
    )


async def _probe(client, family: str, ident: str, name: str) -> list[dict] | None:
    """Return the raw postings for (family, ident), or None on any failure."""
    try:
        cls = get_adapter_cls(family)
    except Exception:  # noqa: BLE001
        return None
    adapter = cls(client=client)
    try:
        raws = await asyncio.wait_for(
            adapter.fetch(_fake_company(family, ident, name)), PROBE_TIMEOUT_S
        )
        return list(raws)
    except Exception:  # noqa: BLE001
        return None


async def _employer_text(client, family: str, ident: str, raws: list[dict]) -> str:
    """Best-effort employer/board display name for the name-vs-content guard."""
    try:
        if family == "greenhouse":
            r = await client.get(
                f"https://boards-api.greenhouse.io/v1/boards/{ident}", timeout=PROBE_TIMEOUT_S
            )
            if r.status_code == 200:
                return str((r.json() or {}).get("name") or "")
        if family == "recruitee" and raws:
            return str(raws[0].get("company_name") or "")
        if family == "smartrecruiters" and raws:
            comp = raws[0].get("company")
            if isinstance(comp, dict):
                return str(comp.get("name") or "")
        if family == "teamtailor" and raws:
            comp = raws[0].get("company")
            if isinstance(comp, dict):
                return str(comp.get("name") or "")
    except Exception:  # noqa: BLE001
        return ""
    return ""


# ---------------------------------------------------------------------------
# Per-company healing
# ---------------------------------------------------------------------------


async def _discover(client, sem, row: dict) -> dict:
    """Concurrent discovery pass: find a candidate that returns jobs."""
    name = row["name"]
    declared = row.get("ats_type", "custom")
    current = row.get("ats_identifier")

    async with sem:
        # 1. Does the current config still work (retry may recover 429s)?
        if declared not in ("custom", "playwright") and current:
            raws = await _probe(client, declared, current, name)
            if raws:
                return {"name": name, "status": "ok", "jobs": len(raws)}

        # 2. Workday: try alternate pods with the same tenant/site.
        if declared == "workday":
            for cand in workday_candidates(current):
                raws = await _probe(client, "workday", cand, name)
                if raws:
                    return {
                        "name": name, "status": "candidate", "jobs": len(raws),
                        "old": (declared, current), "new": ("workday", cand),
                    }
            return {"name": name, "status": "unfixable", "reason": "workday"}

        if declared in ("custom", "playwright"):
            return {"name": name, "status": "unfixable", "reason": declared}

        # 3. Guess alternative family + identifier.
        ids = identifier_candidates(name, current)
        for family in CANDIDATE_FAMILIES:
            for ident in ids:
                if family == declared and ident == current:
                    continue  # already known-bad
                raws = await _probe(client, family, ident, name)
                if raws:
                    return {
                        "name": name, "status": "candidate", "jobs": len(raws),
                        "old": (declared, current), "new": (family, ident),
                    }
        return {"name": name, "status": "broken"}


async def _verify(client, res: dict) -> dict:
    """Sequential verification of a discovered candidate (concurrency 1).

    Confirms the OLD config truly fails, the NEW candidate returns jobs, and the
    name-vs-content guard corroborates the employer. Downgrades to 'ok',
    'needs_review', or 'broken' as appropriate.
    """
    name = res["name"]
    old_family, old_id = res["old"]
    new_family, new_id = res["new"]

    if old_id:
        old_raws = await _probe(client, old_family, old_id, name)
        if old_raws:
            return {"name": name, "status": "ok", "jobs": len(old_raws)}

    new_raws = await _probe(client, new_family, new_id, name)
    if not new_raws:
        return {"name": name, "status": "broken"}

    employer = await _employer_text(client, new_family, new_id, new_raws)
    verdict = name_verdict(name, employer)
    base = {
        "name": name, "jobs": len(new_raws),
        "old": (old_family, old_id), "new": (new_family, new_id),
        "employer": employer, "verdict": verdict,
    }
    if verdict in ("match", "unverified"):
        return {**base, "status": "fixed"}
    # weak name or employer mismatch -> do not auto-apply
    return {**base, "status": "needs_review"}


# ---------------------------------------------------------------------------
# Orchestration + reporting
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON via a temp file + os.replace so a crash can't corrupt seeds."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _write_report(results: list[dict]) -> None:
    REPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "name", "status", "old_ats", "old_id", "new_ats", "new_id",
            "jobs_now", "employer", "verdict",
        ])
        for r in sorted(results, key=lambda x: (x["status"], x["name"])):
            old = r.get("old") or ("", "")
            new = r.get("new") or ("", "")
            w.writerow([
                r["name"], r["status"], old[0], old[1] or "", new[0], new[1] or "",
                r.get("jobs", ""), r.get("employer", ""), r.get("verdict", ""),
            ])


async def _careers_url_alive(client, url: str) -> bool:
    try:
        r = await client.head(url, follow_redirects=True, timeout=PROBE_TIMEOUT_S)
        if r.status_code == 405 or r.status_code >= 400:
            r = await client.get(url, follow_redirects=True, timeout=PROBE_TIMEOUT_S)
        return r.status_code < 400
    except Exception:  # noqa: BLE001
        return False


async def run_heal(dry_run: bool = False, min_ok: int | None = None) -> int:
    """Heal stale seeds. Returns a process exit code (0 = success)."""
    rows = json.loads(SEEDS.read_text(encoding="utf-8"))
    by_name_row = {r["name"]: r for r in rows}
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent},
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        discovered = await asyncio.gather(*(_discover(client, sem, r) for r in rows))

        # Sequential verification for each discovered candidate.
        results: list[dict] = []
        for d in discovered:
            results.append(await _verify(client, d) if d["status"] == "candidate" else d)

        # Add add-company hints for still-broken / needs-review (B.8).
        for r in results:
            if r["status"] in ("broken", "needs_review"):
                url = by_name_row[r["name"]].get("careers_url", "")
                r["careers_url"] = url

    fixed = [r for r in results if r["status"] == "fixed"]
    ok = [r for r in results if r["status"] == "ok"]
    needs_review = [r for r in results if r["status"] == "needs_review"]
    broken = [r for r in results if r["status"] == "broken"]
    unfixable = [r for r in results if r["status"] == "unfixable"]

    by_name = {r["name"]: r for r in results}
    if not dry_run:
        for row in rows:
            res = by_name.get(row["name"])
            if res and res["status"] == "fixed":
                family, ident = res["new"]
                row["ats_type"] = family
                row["ats_identifier"] = ident
                row["careers_url"] = canonical_url(family, ident)
        _atomic_write_json(SEEDS, rows)
    _write_report(results)

    total = len(rows)
    print("=" * 66)
    print(f"Seeds: {total}   ok: {len(ok)}   FIXED: {len(fixed)}   "
          f"needs-review: {len(needs_review)}   broken: {len(broken)}   "
          f"unfixable: {len(unfixable)}")
    print("=" * 66)
    print(f"FIXED ({len(fixed)}):")
    for r in sorted(fixed, key=lambda x: x["name"]):
        o, n = f"{r['old'][0]}:{r['old'][1]}", f"{r['new'][0]}:{r['new'][1]}"
        print(f"  {r['name']:<22} {o:<28} -> {n:<28} ({r['jobs']} jobs)")
    if needs_review:
        print("=" * 66)
        print(f"NEEDS REVIEW ({len(needs_review)}) — candidate found but name not "
              f"corroborated; confirm before trusting:")
        for r in sorted(needs_review, key=lambda x: x["name"]):
            n = f"{r['new'][0]}:{r['new'][1]}"
            emp = f" employer={r['employer']!r}" if r.get("employer") else ""
            print(f"  {r['name']:<22} -> {n:<28} ({r['jobs']} jobs, {r['verdict']}){emp}")
    print("=" * 66)
    print(f"STILL BROKEN ({len(broken)}):")
    for r in sorted(broken, key=lambda x: x["name"]):
        hint = ""
        if r.get("careers_url"):
            hint = f"   -> try: python run.py add-company {r['careers_url']}"
        print(f"  {r['name']}{hint}")

    ok_total = len(ok) + len(fixed)
    if dry_run:
        print(f"\n(dry-run: {SEEDS.name} NOT modified; report at {REPORT_CSV})")
    else:
        print(f"\nWrote {len(fixed)} fixes to {SEEDS}")
        print(f"Report: {REPORT_CSV}")

    # B.9: success threshold.
    if min_ok is not None:
        print(f"\nTarget: >= {min_ok} companies OK. Actual: {ok_total}.")
        if ok_total < min_ok:
            logger.warning("heal-seeds below target ({} < {})", ok_total, min_ok)
            return 1
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Auto-heal stale seed identifiers.")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--min-ok", type=int, default=None,
                    help="exit non-zero if fewer than N companies end up OK")
    args = ap.parse_args()
    code = asyncio.run(run_heal(dry_run=args.dry_run, min_ok=args.min_ok))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
