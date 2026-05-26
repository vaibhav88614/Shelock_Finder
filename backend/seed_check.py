"""Sanity check for `seeds/companies.json`.

Walks every seed entry and issues a HEAD (falling back to a streamed GET, since
some careers sites reject HEAD with 405) to verify the URL is reachable. Prints a
per-ATS summary and writes the full result table to ``data/seed_check.csv``.

This is a manual operator tool — it makes real HTTP requests and is therefore NOT
invoked from any test or from the seed loader. Run it via::

    python run.py check-seeds                # all entries
    python run.py check-seeds --ats lever    # one family
    python run.py check-seeds --timeout 8    # tighter per-request timeout
"""
from __future__ import annotations

import asyncio
import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import httpx
from loguru import logger

from .config import settings
from .detect import detect_ats

_USER_AGENT = "JobPulse/0.1 (+seed-check)"
_DEFAULT_TIMEOUT = 12.0
_CONCURRENCY = 10


@dataclass
class CheckResult:
    name: str
    ats_type: str
    careers_url: str
    status: int | None
    note: str
    detect_match: bool


async def _probe(client: httpx.AsyncClient, name: str, url: str) -> tuple[int | None, str]:
    try:
        r = await client.head(url, follow_redirects=True)
        if r.status_code == 405 or r.status_code >= 400:
            # Many sites refuse HEAD; retry with a streamed GET (no body read).
            async with client.stream("GET", url) as g:
                return g.status_code, "GET-fallback" if r.status_code == 405 else ""
        return r.status_code, ""
    except httpx.TimeoutException:
        return None, "timeout"
    except httpx.HTTPError as exc:
        return None, f"http-error: {type(exc).__name__}"


async def _run(rows: list[dict], timeout: float) -> list[CheckResult]:
    sem = asyncio.Semaphore(_CONCURRENCY)
    results: list[CheckResult] = []
    headers = {"User-Agent": _USER_AGENT, "Accept": "*/*"}
    limits = httpx.Limits(max_connections=_CONCURRENCY * 2)

    async with httpx.AsyncClient(timeout=timeout, headers=headers, limits=limits) as client:
        async def worker(row: dict) -> None:
            async with sem:
                status, note = await _probe(client, row["name"], row["careers_url"])
                detected_type, _ = detect_ats(row["careers_url"])
                match = (detected_type == row.get("ats_type")) or row.get("ats_type") == "custom"
                results.append(
                    CheckResult(
                        name=row["name"],
                        ats_type=row.get("ats_type", "custom"),
                        careers_url=row["careers_url"],
                        status=status,
                        note=note,
                        detect_match=match,
                    )
                )

        await asyncio.gather(*(worker(r) for r in rows))
    return results


def check_seeds(ats: str | None = None, timeout: float = _DEFAULT_TIMEOUT) -> int:
    """Probe every seed URL. Returns count of entries that look unhealthy."""
    path: Path = settings.seeds_dir / "companies.json"
    if not path.exists():
        logger.error("Seed file {} not found.", path)
        return 0
    rows: list[dict] = json.loads(path.read_text(encoding="utf-8"))
    if ats:
        rows = [r for r in rows if r.get("ats_type") == ats]
    if not rows:
        logger.warning("No seed entries matched.")
        return 0

    logger.info("Probing {} careers URLs (concurrency={}, timeout={}s)…", len(rows), _CONCURRENCY, timeout)
    results = asyncio.run(_run(rows, timeout))
    results.sort(key=lambda r: (r.ats_type, r.name))

    # Write CSV
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    out_csv = settings.data_dir / "seed_check.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "ats_type", "careers_url", "status", "note", "detect_match"])
        for r in results:
            w.writerow([r.name, r.ats_type, r.careers_url, r.status or "", r.note, r.detect_match])

    # Per-ATS summary
    by_ats: dict[str, Counter[str]] = {}
    bad = 0
    for r in results:
        bucket = by_ats.setdefault(r.ats_type, Counter())
        ok = (r.status is not None) and (r.status < 400) and r.detect_match
        bucket["ok" if ok else "bad"] += 1
        if not ok:
            bad += 1

    logger.info("--- seed_check summary ---")
    for ats_name in sorted(by_ats):
        c = by_ats[ats_name]
        logger.info("  {:<16} ok={:>3}  bad={:>3}", ats_name, c["ok"], c["bad"])
    logger.info("total bad: {} / {} (csv: {})", bad, len(results), out_csv)
    return bad


if __name__ == "__main__":
    check_seeds()
