"""Auto-infer `custom_selectors` for custom-adapter companies.

Companies ingested via `ingest_india.py` that have an in-house careers page (no
recognized ATS) are registered as `ats_type="custom"` with **no** selectors, so
they return zero jobs. This tool fetches each such careers page and tries to
infer a working `(list_item, title, apply_url)` selector spec by brute-forcing a
ranked set of candidate CSS selectors against the page and keeping the best one
that the real `extract_rows()` engine turns into >= 2 plausible job rows.

Two rendering passes:
  1. Plain HTTP (httpx) — works for server-rendered careers pages.
  2. Playwright fallback (opt-in) — renders JS-heavy pages; a spec inferred from
     rendered HTML is stored with `ats_type="playwright"` (+ a `wait_for` hint)
     so the scrape pipeline renders it too.

Companies where nothing can be inferred keep their existing config (0 jobs) and
are written to `data/selectors_review.csv` for manual configuration. Successful
inferences are applied to `seeds/companies.json` and logged to
`data/selectors_inferred.csv`.

    python run.py infer-selectors                    # httpx only, India custom seeds
    python run.py infer-selectors --playwright       # + Playwright fallback for JS pages
    python run.py infer-selectors --all-custom       # every custom seed, not just India
    python run.py infer-selectors --dry-run          # report only; write nothing
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
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from backend.adapters._html_extract import extract_one, extract_rows
from backend.config import settings

SEEDS = settings.seeds_dir / "companies.json"
INFERRED_CSV = settings.data_dir / "selectors_inferred.csv"
REVIEW_CSV = settings.data_dir / "selectors_review.csv"

FETCH_TIMEOUT_S = 10.0
# Hard ceiling per company so a single slow/trickling host can't stall the
# whole batch beyond the httpx per-request timeout (some careers CDNs keep a
# connection open and drip bytes, extending total time well past FETCH_TIMEOUT_S).
FETCH_HARD_TIMEOUT_S = 14.0
DEFAULT_MAX_WORKERS = 16
MIN_GOOD_ROWS = 2

# Words that identify a job posting title (role families + common tech terms).
_JOB_TITLE_KEYWORDS = (
    "engineer", "developer", "manager", "designer", "analyst", "lead",
    "architect", "consultant", "specialist", "executive", "intern", "trainee",
    "associate", "officer", "administrator", "scientist", "tester", "devops",
    "programmer", "coordinator", "director", "recruiter", "marketing", "sales",
    "support", "product", "project", "business", "data", "cloud", "security",
    "fullstack", "full stack", "frontend", "front end", "front-end", "backend",
    "back end", "back-end", "qa", "sde", "software", "ui/ux", "ux", "ui",
    "python", "java", "javascript", "react", "node", "php", "android", "ios",
    "salesforce", "wordpress", "seo", "content", "hr", "finance", "accountant",
    "operations", "delivery", "technical", "engineering", "graphic", "mobile",
    "wpf", ".net", "dotnet", "golang", "ruby", "flutter", "magento", "shopify",
)

# Substrings marking a URL as a job/apply link.
_JOB_LINK_KEYWORDS = (
    "job", "career", "position", "opening", "vacanc", "apply", "requisition",
    "/jd", "recruit", "hiring", "opportunit", "gh_jid", "lever.co",
    "greenhouse", "myworkdayjobs", "ashbyhq", "smartrecruiters", "workable",
    "/role", "current-opening", "we-are-hiring", "join",
)

# Titles that are almost certainly navigation, not jobs.
_NAV_STOPWORDS = frozenset({
    "home", "about", "about us", "contact", "contact us", "login", "log in",
    "sign in", "sign up", "privacy", "privacy policy", "terms", "blog", "news",
    "services", "products", "portfolio", "faq", "faqs", "support", "help",
    "pricing", "team", "culture", "life", "why us", "benefits", "perks",
    "gallery", "events", "resources", "cookie", "cookies", "read more",
    "learn more", "view all", "see all", "apply now", "know more", "explore",
    "get started", "our work", "case studies", "testimonials", "clients",
    "solutions", "company", "careers", "career", "jobs", "menu", "search",
})

# Ranked list_item candidates: most specific (job-ish containers) first.
_LIST_ITEM_CANDIDATES = (
    'li[class*="job" i]', 'div[class*="job" i]', 'article[class*="job" i]',
    'tr[class*="job" i]',
    'li[class*="career" i]', 'div[class*="career" i]',
    'li[class*="position" i]', 'div[class*="position" i]',
    'li[class*="opening" i]', 'div[class*="opening" i]',
    'li[class*="vacanc" i]', 'div[class*="vacanc" i]',
    'div[class*="listing" i]', 'li[class*="listing" i]',
    '[class*="job-list" i] li', '[class*="jobs" i] li', '[class*="careers" i] li',
    'ul[class*="job" i] li', 'ul[class*="career" i] li',
    'table[class*="job" i] tr', 'tbody tr',
    'article', '.card', 'li', 'div[class*="col" i]',
)

# Broad selectors that also match navigation/footer/marketing rows. They're a
# last resort and only accepted when almost every matched row is a real job
# (high precision), since the stored spec has no job-likeness filter at scrape
# time — a loose selector would otherwise pull in "Blog"/"FAQ"/"Careers" links.
_GENERIC_LIST_ITEMS = frozenset({
    "tbody tr", "article", ".card", "li", 'div[class*="col" i]',
    'div[class*="listing" i]', 'li[class*="listing" i]',
})
_GENERIC_MIN_GOOD = 3
_GENERIC_MIN_RATIO = 0.75

_TITLE_CANDIDATES = (
    "h3", "h2", "h4", "h5",
    '[class*="title" i]', '[class*="role" i]', '[class*="position" i]',
    "a",
)

_APPLY_CANDIDATES = ("a[href]@href", "a@href")

_LOCATION_CANDIDATES = (
    '[class*="location" i]', '[class*="city" i]', '[class*="place" i]',
)


# ---------------------------------------------------------------------------
# Pure heuristics (unit-tested)
# ---------------------------------------------------------------------------


def looks_like_job_title(text: str | None) -> bool:
    if not text:
        return False
    t = " ".join(text.split())
    low = t.lower()
    if low in _NAV_STOPWORDS:
        return False
    if not (3 <= len(t) <= 120):
        return False
    words = t.split()
    if not (1 <= len(words) <= 14):
        return False
    if not re.search(r"[a-zA-Z]", t):
        return False
    return True


def title_has_job_keyword(text: str | None) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(k in low for k in _JOB_TITLE_KEYWORDS)


def looks_like_job_link(url: str | None) -> bool:
    if not url:
        return False
    low = url.lower()
    return any(k in low for k in _JOB_LINK_KEYWORDS)


def _row_is_job(row: dict) -> bool:
    """A row counts as a real posting if its link is job-like, or its title
    carries a role keyword (and isn't obvious navigation)."""
    title = row.get("title")
    if title and " ".join(title.split()).lower() in _NAV_STOPWORDS:
        return False
    return looks_like_job_link(row.get("apply_url")) or (
        looks_like_job_title(title) and title_has_job_keyword(title)
    )


def _build_rows(elements, title_sel: str, apply_sel: str, base_url: str) -> list[dict]:
    """Extract (title, apply_url) rows from pre-selected list-item elements.

    Mirrors `extract_rows` (same `extract_one` + absolutize logic) but reuses an
    already-parsed element list so candidate scoring doesn't re-parse the HTML.
    """
    from urllib.parse import urljoin

    rows: list[dict] = []
    seen: set[str] = set()
    for el in elements:
        title = extract_one(el, title_sel)
        apply_url = extract_one(el, apply_sel)
        if not title or not apply_url:
            continue
        if apply_url.startswith("/") or not apply_url.startswith(("http://", "https://")):
            apply_url = urljoin(base_url, apply_url)
        if apply_url in seen:
            continue
        seen.add(apply_url)
        rows.append({"title": title, "apply_url": apply_url})
    return rows


def infer_selectors(html: str, page_url: str) -> dict | None:
    """Infer a `custom_selectors` spec for `html`, or None if nothing fits.

    Brute-forces ranked candidate (list_item, title, apply_url) triples and
    keeps the highest-scoring spec that yields >= MIN_GOOD_ROWS plausible job
    rows with a decent good/total ratio. The HTML is parsed ONCE and every
    candidate is evaluated against the cached tree. A `location` selector is
    added when it resolves for a majority of matched rows.
    """
    soup = BeautifulSoup(html, "html.parser")
    best: dict | None = None
    best_key: tuple = (0, 0.0)
    for li in _LIST_ITEM_CANDIDATES:
        try:
            elements = soup.select(li)
        except Exception:  # noqa: BLE001 — invalid selector for this tree
            continue
        # Skip empty matches and pathologically broad ones (e.g. "li" matching
        # a giant nav) that would dominate scoring with noise.
        if not elements or len(elements) > 500:
            continue
        is_generic = li in _GENERIC_LIST_ITEMS
        min_good = _GENERIC_MIN_GOOD if is_generic else MIN_GOOD_ROWS
        min_ratio = _GENERIC_MIN_RATIO if is_generic else 0.4
        for title in _TITLE_CANDIDATES:
            for apply in _APPLY_CANDIDATES:
                rows = _build_rows(elements, title, apply, page_url)
                if not rows:
                    continue
                good = sum(1 for r in rows if _row_is_job(r))
                if good < min_good:
                    continue
                ratio = good / len(rows)
                if ratio < min_ratio:
                    continue
                key = (good, ratio)
                if key > best_key:
                    best_key = key
                    best = {
                        "list_url": page_url,
                        "list_item": li,
                        "title": title,
                        "apply_url": apply,
                    }
        # Early exit: a strong precise match on an early (specific) candidate.
        if best is not None and best_key[0] >= MIN_GOOD_ROWS and best_key[1] >= 0.8:
            break
    if best is None:
        return None
    _augment_location(soup, best, page_url)
    return best


def _augment_location(soup: BeautifulSoup, spec: dict, base_url: str) -> None:
    """Add a `location` selector to `spec` if one resolves for most rows."""
    try:
        elements = soup.select(spec["list_item"])
    except Exception:  # noqa: BLE001
        return
    rows_total = _build_rows(elements, spec["title"], spec["apply_url"], base_url)
    if not rows_total:
        return
    for loc in _LOCATION_CANDIDATES:
        with_loc = 0
        seen: set[str] = set()
        for el in elements:
            title = extract_one(el, spec["title"])
            apply_url = extract_one(el, spec["apply_url"])
            if not title or not apply_url or apply_url in seen:
                continue
            seen.add(apply_url)
            if extract_one(el, loc):
                with_loc += 1
        if with_loc >= max(1, len(rows_total) // 2):
            spec["location"] = loc
            return


# ---------------------------------------------------------------------------
# Fetching (network)
# ---------------------------------------------------------------------------


async def fetch_html(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await asyncio.wait_for(
            client.get(
                url,
                headers={"Accept": "text/html,application/xhtml+xml"},
                timeout=FETCH_TIMEOUT_S,
                follow_redirects=True,
            ),
            FETCH_HARD_TIMEOUT_S,
        )
    except (httpx.HTTPError, asyncio.TimeoutError):
        return None
    if r.status_code >= 400 or not r.text:
        return None
    return r.text


async def render_html_playwright(context, url: str) -> str | None:  # noqa: ANN001
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(1800)
        return await page.content()
    except Exception as e:  # noqa: BLE001
        logger.debug("Playwright render failed for {}: {}", url, e)
        return None
    finally:
        await page.close()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _targets(
    rows: list[dict], all_custom: bool, country: str | None, refresh: bool = False
) -> list[dict]:
    out = []
    for r in rows:
        # In refresh mode also re-process companies previously switched to
        # playwright by an earlier inference run.
        allowed_types = {"custom", "playwright"} if refresh else {"custom"}
        if r.get("ats_type") not in allowed_types:
            continue
        if r.get("custom_selectors") and not refresh:
            continue
        if not all_custom and country and (r.get("country") or "") != country:
            continue
        out.append(r)
    return out


async def _infer_httpx(client, sem, row: dict) -> dict:
    """httpx pass for one company. Returns a result dict."""
    url = row.get("careers_url") or ""
    name = row["name"]
    async with sem:
        html = await fetch_html(client, url)
    if not html:
        return {"name": name, "url": url, "status": "no_html"}
    spec = infer_selectors(html, url)
    if spec is None:
        return {"name": name, "url": url, "status": "no_match", "html_len": len(html)}
    return {"name": name, "url": url, "status": "inferred", "ats_type": "custom", "spec": spec}


async def _infer_playwright(context, row: dict) -> dict:
    """Playwright pass for one company whose httpx attempt found nothing."""
    url = row.get("careers_url") or ""
    name = row["name"]
    html = await render_html_playwright(context, url)
    if not html:
        return {"name": name, "url": url, "status": "no_html"}
    spec = infer_selectors(html, url)
    if spec is None:
        return {"name": name, "url": url, "status": "no_match", "html_len": len(html)}
    # Rendered-only match -> must be scraped with Playwright too.
    spec["wait_for"] = spec["list_item"]
    return {"name": name, "url": url, "status": "inferred", "ats_type": "playwright", "spec": spec}


def _apply_results(
    rows: list[dict], results: dict[str, dict], target_names: set[str], refresh: bool
) -> int:
    applied = 0
    for row in rows:
        res = results.get(row["name"])
        if res and res.get("status") == "inferred":
            row["custom_selectors"] = res["spec"]
            row["ats_type"] = res["ats_type"]
            applied += 1
        elif refresh and row["name"] in target_names:
            # Re-inference no longer matches: clear any stale spec so the
            # company reverts to a plain (job-less) custom entry rather than
            # keeping an outdated/low-precision selector set.
            if row.get("custom_selectors"):
                row["custom_selectors"] = None
            row["ats_type"] = "custom"
    return applied


def _write_reports(inferred: list[dict], review: list[dict]) -> None:
    INFERRED_CSV.parent.mkdir(parents=True, exist_ok=True)
    with INFERRED_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "careers_url", "ats_type", "list_item", "title", "apply_url", "location"])
        for r in sorted(inferred, key=lambda x: x["name"].lower()):
            s = r["spec"]
            w.writerow([
                r["name"], r["url"], r["ats_type"], s.get("list_item", ""),
                s.get("title", ""), s.get("apply_url", ""), s.get("location", ""),
            ])
    with REVIEW_CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "careers_url", "reason"])
        for r in sorted(review, key=lambda x: x["name"].lower()):
            w.writerow([r["name"], r["url"], r["status"]])


async def run_infer(
    all_custom: bool = False,
    country: str | None = "India",
    use_playwright: bool = False,
    max_playwright: int = 80,
    max_workers: int = DEFAULT_MAX_WORKERS,
    dry_run: bool = False,
    refresh: bool = False,
) -> int:
    rows = json.loads(SEEDS.read_text(encoding="utf-8"))
    targets = _targets(rows, all_custom, country, refresh=refresh)
    target_names = {r["name"] for r in targets}
    logger.info(
        "infer-selectors: {} custom companies to process ({}).",
        len(targets), "refresh: re-inferring all" if refresh else "without selectors",
    )
    if not targets:
        _write_reports([], [])
        return 0

    results: dict[str, dict] = {}
    sem = asyncio.Semaphore(max_workers)
    async with httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent},
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        httpx_results = await asyncio.gather(*(_infer_httpx(client, sem, r) for r in targets))
    for r in httpx_results:
        results[r["name"]] = r

    inferred_httpx = sum(1 for r in results.values() if r["status"] == "inferred")
    logger.info("httpx pass: {} inferred, {} unresolved.", inferred_httpx, len(targets) - inferred_httpx)

    # Playwright fallback for the unresolved ones (bounded).
    if use_playwright:
        misses = [r for r in targets if results[r["name"]]["status"] != "inferred"]
        misses = misses[:max_playwright]
        if misses:
            pw_done = await _run_playwright_pass(misses, results)
            logger.info("playwright pass: {} newly inferred (of {} tried).", pw_done, len(misses))

    inferred = [r for r in results.values() if r["status"] == "inferred"]
    review = [r for r in results.values() if r["status"] != "inferred"]

    applied = 0
    if not dry_run:
        applied = _apply_results(rows, results, target_names, refresh)
        _atomic_write_json(SEEDS, rows)
    _write_reports(inferred, review)

    print("=" * 66)
    print(f"infer-selectors: targets={len(targets)}  inferred={len(inferred)}  "
          f"needs-review={len(review)}  applied_to_seeds={applied}")
    print("=" * 66)
    print(f"Inferred report: {INFERRED_CSV}")
    print(f"Review list:     {REVIEW_CSV}")
    if dry_run:
        print(f"\n(dry-run: {SEEDS.name} NOT modified)")
    else:
        print(f"\nUpdated {applied} companies in {SEEDS}. Run `python run.py seed` to apply to the DB.")
    return 0


async def _run_playwright_pass(misses: list[dict], results: dict[str, dict]) -> int:
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except ImportError:
        logger.warning("playwright not installed; skipping Playwright fallback.")
        return 0
    done = 0
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=settings.user_agent)
                sem = asyncio.Semaphore(4)

                async def _one(row: dict) -> None:
                    nonlocal done
                    async with sem:
                        res = await _infer_playwright(context, row)
                    results[row["name"]] = res
                    if res["status"] == "inferred":
                        done += 1

                await asyncio.gather(*(_one(r) for r in misses))
            finally:
                await browser.close()
    except Exception as e:  # noqa: BLE001 — e.g. chromium not installed
        logger.warning(
            "Playwright fallback unavailable ({}). Run `playwright install chromium` "
            "to enable JS-rendered inference.", e,
        )
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description="Auto-infer custom_selectors for custom-adapter companies.")
    ap.add_argument("--all-custom", action="store_true",
                    help="Process every custom company, not just country=India.")
    ap.add_argument("--country", default="India",
                    help="Restrict to this country (default India; ignored with --all-custom).")
    ap.add_argument("--playwright", action="store_true",
                    help="Enable the Playwright fallback for JS-rendered pages.")
    ap.add_argument("--max-playwright", type=int, default=80,
                    help="Cap the number of Playwright renders (bounds runtime).")
    ap.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    ap.add_argument("--refresh", action="store_true",
                    help="Re-infer companies that already have selectors (overwrite/clear).")
    ap.add_argument("--dry-run", action="store_true", help="Report only; don't modify seeds.")
    args = ap.parse_args()

    code = asyncio.run(
        run_infer(
            all_custom=args.all_custom,
            country=None if args.all_custom else args.country,
            use_playwright=args.playwright,
            max_playwright=args.max_playwright,
            max_workers=args.max_workers,
            dry_run=args.dry_run,
            refresh=args.refresh,
        )
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
