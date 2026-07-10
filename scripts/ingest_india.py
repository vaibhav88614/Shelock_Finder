"""Ingest India-based tech companies into seeds/companies.json.

Pulls candidate companies from three sources:

  1. The GoodFirms Excel export shipped in the repo (marketing homepage URLs).
  2. Additional GoodFirms India directories, scraped live with Playwright
     (GoodFirms is behind Cloudflare and returns 403 to plain HTTP, so a real
     browser is required; the scrape is best-effort and skipped if Playwright
     is unavailable).
  3. A curated JSON list of well-known Indian tech companies
     (`scripts/india_curated.json`).

For every candidate it:

  * cleans the homepage URL (strips utm_*/ref tracking params, drops fragments),
  * discovers a working careers source — first scanning the homepage HTML for a
    known ATS link (Greenhouse/Lever/Ashby/Workable/SmartRecruiters/Recruitee/
    Teamtailor/Personio/Workday), then falling back to probing common
    `/careers`-style paths and registering as a `custom` adapter,
  * runs a 5x HTTP sanity check against the discovered careers URL and DROPS the
    company entirely if all five attempts fail,
  * merges survivors into `seeds/companies.json` with `country="India"`,
    preserving the existing entries verbatim.

Audit trails are written to `data/india_ingest_report.csv` (kept) and
`data/india_ingest_dropped.csv` (dropped, with reason).

    python run.py ingest-india                       # excel + curated, no live GoodFirms
    python run.py ingest-india --from-goodfirms all  # also scrape GoodFirms live
    python run.py ingest-india --dry-run             # report only; write nothing
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import re
import zipfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from backend.config import settings
from backend.detect import detect_ats

SEEDS = settings.seeds_dir / "companies.json"
REPORT_CSV = settings.data_dir / "india_ingest_report.csv"
DROPPED_CSV = settings.data_dir / "india_ingest_dropped.csv"
CURATED = Path(__file__).resolve().parent / "india_curated.json"

# GoodFirms India directories to scrape live (short name -> path under the host).
GOODFIRMS_CATEGORIES: dict[str, str] = {
    "python": "directory/country/top-software-development-companies/python/india",
    "java": "directory/country/top-software-development-companies/java/india",
    "php": "directory/country/top-software-development-companies/php/india",
    "javascript": "directory/country/top-software-development-companies/javascript/india",
    "nodejs": "directory/country/top-software-development-companies/nodejs/india",
    "mobile": "directory/country/top-mobile-app-development-companies/india",
    "web": "directory/country/top-web-development-companies/india",
    "ai": "directory/country/top-artificial-intelligence-companies/india",
}

# Careers paths probed (in order) when no ATS link is found on the homepage.
CAREER_PATHS = (
    "/careers",
    "/careers/",
    "/jobs",
    "/careers.html",
    "/career",
    "/join-us",
    "/work-with-us",
    "/openings",
    "/hiring",
    "/about/careers",
)

# Host substrings that mark a link as belonging to a known ATS family.
ATS_HOST_HINTS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "workable.com",
    "smartrecruiters.com",
    "recruitee.com",
    "teamtailor.com",
    "personio.",
    "myworkdayjobs.com",
)

# Query-string keys stripped from URLs before use / dedupe.
_TRACKING_KEYS = {"ref", "referrer", "source", "fbclid", "gclid", "mc_cid", "mc_eid"}

HOMEPAGE_TIMEOUT_S = 12.0
PROBE_TIMEOUT_S = 12.0
DEFAULT_SANITY_ROUNDS = 5
DEFAULT_SANITY_SPACING_S = 2.0
DEFAULT_MAX_WORKERS = 10
DEFAULT_GOODFIRMS_PAGES = 15


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested; no network)
# ---------------------------------------------------------------------------


def clean_url(url: str | None) -> str:
    """Strip utm_*/ref tracking params and any fragment; ensure a scheme."""
    if not url:
        return ""
    url = url.strip()
    parts = urlsplit(url if "://" in url else f"https://{url}")
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_KEYS
    ]
    return urlunsplit(
        (parts.scheme or "https", parts.netloc, parts.path, urlencode(kept), "")
    )


def host_of(url: str | None) -> str:
    """Normalized bare host of a URL (lowercased, no `www.`, no port)."""
    if not url:
        return ""
    parts = urlsplit(url if "://" in url else f"https://{url}")
    host = (parts.netloc or "").lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def homepage_base(url: str | None) -> str:
    """Scheme + host root of a URL, with tracking params/paths dropped."""
    cleaned = clean_url(url)
    parts = urlsplit(cleaned)
    return urlunsplit((parts.scheme or "https", parts.netloc, "", "", ""))


def extract_ats_links(html: str, base_url: str | None = None) -> list[str]:
    """Return absolute links in `html` whose host looks like a known ATS."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base_url or "", href)
        host = host_of(full)
        if any(hint in host for hint in ATS_HOST_HINTS) and full not in seen:
            seen.add(full)
            out.append(full)
    return out


def parse_goodfirms_cards(html: str) -> list[tuple[str, str]]:
    """Best-effort (name, homepage) extraction from a GoodFirms directory page.

    GoodFirms renders one external "visit website" anchor per company card,
    carrying utm markers (utm_source=good-firms / utm_medium=listing). We pair
    each such anchor with the nearest company name (its own text/title, or the
    closest heading / profile-link in its ancestor card).
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    seen_hosts: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        if "utm_source=good" not in href and "utm_medium=listing" not in href:
            continue
        home = clean_url(href)
        host = host_of(home)
        if not host or host in seen_hosts or "goodfirms.co" in host:
            continue
        name = _card_name(a)
        if name:
            seen_hosts.add(host)
            out.append((name, home))
    return out


def _card_name(anchor) -> str:  # noqa: ANN001
    """Derive a company name for a GoodFirms external-website anchor."""
    title = (anchor.get("title") or "").strip()
    if title and "website" not in title.lower():
        return title
    text = anchor.get_text(" ", strip=True)
    if text and "website" not in text.lower():
        return text
    # Walk up a few ancestors looking for a heading or a /company/ profile link.
    node = anchor
    for _ in range(6):
        node = node.parent
        if node is None:
            break
        heading = node.find(["h2", "h3", "h4"])
        if heading:
            t = heading.get_text(" ", strip=True)
            if t:
                return t
        prof = node.find("a", href=re.compile(r"/company/"))
        if prof:
            t = prof.get_text(" ", strip=True)
            if t:
                return t
    return ""


def dedupe_candidates(candidates: list[dict]) -> list[dict]:
    """De-duplicate {name, homepage} dicts by cleaned host (first wins)."""
    out: list[dict] = []
    seen: set[str] = set()
    for c in candidates:
        host = host_of(c.get("homepage"))
        if not host or host in seen:
            continue
        seen.add(host)
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# Minimal dependency-free .xlsx reader (avoids adding openpyxl)
# ---------------------------------------------------------------------------

_XL_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _read_xlsx(path: Path) -> list[dict[str, str]]:
    """Read the first worksheet of an .xlsx into a list of header->value dicts."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{_XL_NS}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{_XL_NS}t")))
        sheet_path = "xl/worksheets/sheet1.xml"
        if sheet_path not in names:
            sheet_path = next(
                (n for n in names if n.startswith("xl/worksheets/") and n.endswith(".xml")),
                sheet_path,
            )
        root = ET.fromstring(z.read(sheet_path))
        data = root.find(f"{_XL_NS}sheetData")
        rows: list[dict[str, str]] = []
        if data is None:
            return []
        for row in data.findall(f"{_XL_NS}row"):
            cells: dict[str, str] = {}
            for c in row.findall(f"{_XL_NS}c"):
                ref = c.get("r") or ""
                m = re.match(r"[A-Z]+", ref)
                col = m.group(0) if m else ref
                ctype = c.get("t")
                v = c.find(f"{_XL_NS}v")
                if ctype == "s":
                    val = shared[int(v.text)] if v is not None and v.text else ""
                elif ctype == "inlineStr":
                    is_node = c.find(f"{_XL_NS}is")
                    val = (
                        "".join(x.text or "" for x in is_node.iter(f"{_XL_NS}t"))
                        if is_node is not None
                        else ""
                    )
                else:
                    val = v.text if v is not None and v.text is not None else ""
                cells[col] = val
            rows.append(cells)
    if not rows:
        return []
    header = rows[0]
    out: list[dict[str, str]] = []
    for r in rows[1:]:
        out.append({header.get(col, col): r.get(col, "") for col in header})
    return out


# ---------------------------------------------------------------------------
# Source loaders
# ---------------------------------------------------------------------------


def _default_excel_path() -> Path | None:
    matches = sorted(settings.seeds_dir.parent.glob("dataset_goodfirms*.xlsx"))
    return matches[0] if matches else None


def load_excel(path: Path) -> list[dict]:
    rows = _read_xlsx(path)
    out: list[dict] = []
    for r in rows:
        name = (r.get("companyName") or "").strip()
        # `companyWebsite` is only the external site for sponsored rows; for
        # most rows it's a relative GoodFirms profile path (/company/...) and
        # the real homepage lives in `altWebsite`. Prefer whichever column
        # actually carries a host.
        candidates = [
            (r.get("companyWebsite") or "").strip(),
            (r.get("altWebsite") or "").strip(),
        ]
        homepage = next((c for c in candidates if host_of(c)), "")
        if name and homepage:
            out.append({"name": name, "homepage": homepage, "source": "excel"})
    logger.info("Excel: {} companies loaded from {}", len(out), path.name)
    return out


def load_curated(path: Path = CURATED) -> list[dict]:
    if not path.exists():
        logger.warning("Curated file {} not found; skipping.", path)
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict] = []
    for r in data:
        name = (r.get("name") or "").strip()
        home = (r.get("homepage") or r.get("careers_url") or "").strip()
        if not name or not home:
            continue
        entry = {"name": name, "homepage": home, "source": "curated"}
        # Allow curated entries to pin a known ATS directly.
        if r.get("ats_type"):
            entry["ats_type"] = r["ats_type"]
            entry["ats_identifier"] = r.get("ats_identifier")
            entry["careers_url"] = r.get("careers_url") or home
        out.append(entry)
    logger.info("Curated: {} companies loaded.", len(out))
    return out


async def load_goodfirms(
    categories: list[str],
    max_pages: int = DEFAULT_GOODFIRMS_PAGES,
    page_delay_s: float = 3.0,
) -> list[dict]:
    """Scrape GoodFirms India directories with Playwright (best-effort)."""
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except ImportError:
        logger.warning(
            "playwright not installed; skipping live GoodFirms scrape "
            "(install with `pip install playwright && playwright install chromium`)."
        )
        return []

    results: dict[str, dict] = {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(user_agent=settings.user_agent)
            for cat in categories:
                path = GOODFIRMS_CATEGORIES.get(cat)
                if not path:
                    logger.warning("Unknown GoodFirms category {!r}; skipping.", cat)
                    continue
                for pageno in range(1, max_pages + 1):
                    url = f"https://www.goodfirms.co/{path}?page={pageno}"
                    page = await context.new_page()
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                        await page.wait_for_timeout(1500)
                        html = await page.content()
                    except Exception as e:  # noqa: BLE001
                        logger.warning("GoodFirms {} page {} failed: {}", cat, pageno, e)
                        await page.close()
                        continue
                    await page.close()
                    cards = parse_goodfirms_cards(html)
                    new = 0
                    for name, home in cards:
                        host = host_of(home)
                        if host and host not in results:
                            results[host] = {
                                "name": name, "homepage": home, "source": f"goodfirms:{cat}"
                            }
                            new += 1
                    logger.info(
                        "GoodFirms {} page {}: {} cards, {} new (running total {})",
                        cat, pageno, len(cards), new, len(results),
                    )
                    if not cards:
                        break
                    await asyncio.sleep(page_delay_s)
        finally:
            await browser.close()
    return list(results.values())


# ---------------------------------------------------------------------------
# Careers discovery + sanity check (network)
# ---------------------------------------------------------------------------


async def _head_or_get(client: httpx.AsyncClient, url: str) -> int | None:
    """Return an HTTP status code for `url` (HEAD, falling back to GET), or None."""
    try:
        r = await client.head(url, timeout=PROBE_TIMEOUT_S, follow_redirects=True)
        if r.status_code == 405 or r.status_code >= 400:
            async with client.stream(
                "GET", url, timeout=PROBE_TIMEOUT_S, follow_redirects=True
            ) as g:
                return g.status_code
        return r.status_code
    except httpx.HTTPError:
        return None


async def discover_careers(
    client: httpx.AsyncClient, homepage: str
) -> tuple[str, str, str | None] | None:
    """Find a careers source for `homepage`.

    Returns `(careers_url, ats_type, ats_identifier)` or None if nothing works.
    ATS links found on the homepage win; otherwise the first reachable
    `/careers`-style path is registered as a `custom` adapter.
    """
    homepage = clean_url(homepage)
    base = homepage_base(homepage)
    if not base:
        return None

    # 1. Scan the homepage for an ATS link.
    try:
        r = await client.get(homepage, timeout=HOMEPAGE_TIMEOUT_S, follow_redirects=True)
        if r.status_code < 400 and r.text:
            for link in extract_ats_links(r.text, str(r.url)):
                ats_type, ident = detect_ats(link)
                if ats_type and ident:
                    return (clean_url(link), ats_type, ident)
    except httpx.HTTPError:
        pass

    # 2. Probe common careers paths; first reachable one wins (custom adapter).
    for path in CAREER_PATHS:
        cand = base + path
        code = await _head_or_get(client, cand)
        if code is not None and code < 400:
            return (cand, "custom", None)
    return None


async def sanity_check(
    client: httpx.AsyncClient,
    url: str,
    rounds: int = DEFAULT_SANITY_ROUNDS,
    spacing_s: float = DEFAULT_SANITY_SPACING_S,
) -> tuple[bool, str]:
    """Probe `url` up to `rounds` times. Pass if ANY attempt returns < 400."""
    notes: list[str] = []
    for i in range(rounds):
        code = await _head_or_get(client, url)
        notes.append(str(code) if code is not None else "err")
        if code is not None and code < 400:
            return True, f"ok@{i + 1} [{','.join(notes)}]"
        if i < rounds - 1:
            await asyncio.sleep(spacing_s + random.uniform(0.0, 0.5))
    return False, f"all-{rounds}-failed [{','.join(notes)}]"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


async def _process_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    entry: dict,
    sanity_rounds: int,
    sanity_spacing_s: float,
) -> dict:
    """Discover careers + sanity-check a single candidate. Returns a result dict."""
    name = entry["name"]
    homepage = entry.get("homepage", "")
    async with sem:
        # Curated entries may pin a known ATS; otherwise discover.
        if entry.get("ats_type"):
            careers_url = entry.get("careers_url") or homepage
            ats_type = entry["ats_type"]
            ats_id = entry.get("ats_identifier")
        else:
            found = await discover_careers(client, homepage)
            if found is None:
                return {
                    "name": name, "homepage": homepage, "status": "dropped",
                    "reason": "no careers source discovered",
                }
            careers_url, ats_type, ats_id = found

        ok, note = await sanity_check(client, careers_url, sanity_rounds, sanity_spacing_s)
        if not ok:
            return {
                "name": name, "homepage": homepage, "careers_url": careers_url,
                "ats_type": ats_type, "ats_identifier": ats_id,
                "status": "dropped", "reason": f"sanity failed: {note}",
            }
        return {
            "name": name, "homepage": homepage, "careers_url": careers_url,
            "ats_type": ats_type, "ats_identifier": ats_id,
            "status": "kept", "reason": note,
        }


def _write_report(kept: list[dict], dropped: list[dict]) -> None:
    REPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["name", "homepage", "careers_url", "ats_type", "ats_identifier", "sanity"]
        )
        for r in sorted(kept, key=lambda x: x["name"].lower()):
            w.writerow([
                r["name"], r.get("homepage", ""), r.get("careers_url", ""),
                r.get("ats_type", ""), r.get("ats_identifier") or "", r.get("reason", ""),
            ])
    with DROPPED_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "homepage", "careers_url", "reason"])
        for r in sorted(dropped, key=lambda x: x["name"].lower()):
            w.writerow([
                r["name"], r.get("homepage", ""), r.get("careers_url", ""),
                r.get("reason", ""),
            ])


async def run_ingest(
    from_excel: Path | None = None,
    goodfirms_categories: list[str] | None = None,
    from_curated: bool = True,
    dry_run: bool = False,
    max_workers: int = DEFAULT_MAX_WORKERS,
    sanity_rounds: int = DEFAULT_SANITY_ROUNDS,
    sanity_spacing_s: float = DEFAULT_SANITY_SPACING_S,
    goodfirms_pages: int = DEFAULT_GOODFIRMS_PAGES,
) -> int:
    """Ingest India companies into seeds. Returns process exit code (0 = ok)."""
    existing = json.loads(SEEDS.read_text(encoding="utf-8")) if SEEDS.exists() else []
    existing_names = {str(r.get("name", "")).strip().lower() for r in existing}

    # --- gather candidates -------------------------------------------------
    candidates: list[dict] = []
    if from_excel is not None:
        candidates += load_excel(from_excel)
    if from_curated:
        candidates += load_curated()
    if goodfirms_categories:
        candidates += await load_goodfirms(goodfirms_categories, max_pages=goodfirms_pages)

    candidates = dedupe_candidates(candidates)
    # Drop candidates whose name already exists in seeds (seed name is unique).
    fresh = [c for c in candidates if c["name"].strip().lower() not in existing_names]
    logger.info(
        "Candidates: {} total, {} after dedupe/new-name filter (existing seeds: {}).",
        len(candidates), len(fresh), len(existing),
    )
    if not fresh:
        logger.warning("No new India candidates to ingest.")
        _write_report([], [])
        return 0

    # --- discover + sanity check concurrently ------------------------------
    sem = asyncio.Semaphore(max_workers)
    async with httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent, "Accept": "*/*"},
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        results = await asyncio.gather(
            *(
                _process_one(client, sem, c, sanity_rounds, sanity_spacing_s)
                for c in fresh
            )
        )

    kept = [r for r in results if r["status"] == "kept"]
    dropped = [r for r in results if r["status"] == "dropped"]

    # --- merge kept into seeds (guard against in-batch name collisions) ----
    added = 0
    seen_names = set(existing_names)
    new_rows: list[dict] = []
    for r in sorted(kept, key=lambda x: x["name"].lower()):
        key = r["name"].strip().lower()
        if key in seen_names:
            continue
        seen_names.add(key)
        new_rows.append({
            "name": r["name"].strip(),
            "careers_url": r["careers_url"],
            "ats_type": r["ats_type"],
            "ats_identifier": r.get("ats_identifier"),
            "country": "India",
        })
        added += 1

    if not dry_run:
        _atomic_write_json(SEEDS, existing + new_rows)
    _write_report(kept, dropped)

    print("=" * 66)
    print(
        f"India ingest: candidates={len(fresh)}  kept={len(kept)}  "
        f"dropped={len(dropped)}  added_to_seeds={added}"
    )
    print("=" * 66)
    print(f"Report:  {REPORT_CSV}")
    print(f"Dropped: {DROPPED_CSV}")
    if dry_run:
        print(f"\n(dry-run: {SEEDS.name} NOT modified)")
    else:
        print(f"\nWrote {added} new India companies to {SEEDS}")
        print("Next: `python run.py seed` to load them into the DB.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_goodfirms_arg(value: str | None) -> list[str]:
    if not value:
        return []
    if value.strip().lower() == "all":
        return list(GOODFIRMS_CATEGORIES.keys())
    cats = [c.strip().lower() for c in value.split(",") if c.strip()]
    return [c for c in cats if c in GOODFIRMS_CATEGORIES]


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest India-based tech companies into seeds.")
    ap.add_argument("--from-excel", default=None,
                    help="Path to the GoodFirms .xlsx (default: dataset_goodfirms*.xlsx in repo root).")
    ap.add_argument("--no-excel", action="store_true", help="Skip the Excel source.")
    ap.add_argument("--no-curated", action="store_true", help="Skip the curated JSON source.")
    ap.add_argument("--from-goodfirms", default=None,
                    help="Live-scrape GoodFirms directories: 'all' or a comma list "
                         f"({', '.join(GOODFIRMS_CATEGORIES)}). Requires Playwright.")
    ap.add_argument("--goodfirms-pages", type=int, default=DEFAULT_GOODFIRMS_PAGES,
                    help="Max pages per GoodFirms category.")
    ap.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    ap.add_argument("--sanity-rounds", type=int, default=DEFAULT_SANITY_ROUNDS)
    ap.add_argument("--sanity-spacing", type=float, default=DEFAULT_SANITY_SPACING_S,
                    help="Seconds between sanity-check attempts.")
    ap.add_argument("--dry-run", action="store_true", help="Report only; don't modify seeds.")
    args = ap.parse_args()

    excel_path: Path | None = None
    if not args.no_excel:
        excel_path = Path(args.from_excel) if args.from_excel else _default_excel_path()
        if excel_path is None:
            logger.warning("No Excel file found; continuing without the Excel source.")

    code = asyncio.run(
        run_ingest(
            from_excel=excel_path,
            goodfirms_categories=_parse_goodfirms_arg(args.from_goodfirms),
            from_curated=not args.no_curated,
            dry_run=args.dry_run,
            max_workers=args.max_workers,
            sanity_rounds=args.sanity_rounds,
            sanity_spacing_s=args.sanity_spacing,
            goodfirms_pages=args.goodfirms_pages,
        )
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
