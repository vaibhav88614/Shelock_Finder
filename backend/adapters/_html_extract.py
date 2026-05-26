"""Selector helpers shared by `CustomAdapter` (BeautifulSoup) and
`PlaywrightAdapter` (rendered DOM dumped to HTML and reparsed with BS4).

A selector is a CSS selector with an optional `@attr` suffix:
    "h3.title"        -> element text
    "a.apply@href"    -> attribute value of the matched element
    "time@datetime"   -> attribute value

`custom_selectors` JSON on the `companies` table looks like:

    {
      "list_url":        "https://example.com/careers",   # optional, overrides careers_url
      "list_item":       ".job-row",                        # REQUIRED, the row
      "title":           "h3",                              # REQUIRED
      "apply_url":       "a.apply@href",                    # REQUIRED (rel→abs)
      "location":        ".location",                       # optional
      "department":      ".dept",                           # optional
      "employment_type": ".type",                           # optional
      "posted_date":     "time@datetime",                   # optional
      "description":     ".excerpt",                        # optional (cheap)
      "detail_link":     "a.apply@href",                    # optional: fetch detail
      "detail_description": ".job-description"              # only used if detail_link set
    }
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag


REQUIRED_KEYS = ("list_item", "title", "apply_url")


def validate_selectors(spec: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError("custom_selectors must be a JSON object")
    missing = [k for k in REQUIRED_KEYS if not (isinstance(spec.get(k), str) and spec.get(k).strip())]
    if missing:
        raise ValueError(f"custom_selectors missing required keys: {missing}")
    return spec


def _split_selector(sel: str) -> tuple[str, str | None]:
    """Split `"a.apply@href"` into `("a.apply", "href")`. `"@"` inside attribute
    selectors like `[data-x@y]` is preserved by taking the LAST `@` outside `[...]`."""
    sel = sel.strip()
    depth = 0
    last_at = -1
    for i, ch in enumerate(sel):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "@" and depth == 0:
            last_at = i
    if last_at == -1:
        return sel, None
    return sel[:last_at].strip(), sel[last_at + 1:].strip() or None


def extract_one(scope: Tag, sel: str | None) -> str | None:
    """Run a selector against `scope` and return text or attribute. None if missing."""
    if not sel:
        return None
    css, attr = _split_selector(sel)
    if not css:
        return None
    el = scope.select_one(css)
    if el is None:
        return None
    if attr:
        val = el.get(attr)
        if isinstance(val, list):
            val = " ".join(str(v) for v in val)
        return (val.strip() if isinstance(val, str) else None) or None
    text = el.get_text(" ", strip=True)
    return text or None


def extract_rows(html: str, spec: dict[str, Any], base_url: str) -> list[dict[str, str | None]]:
    """Parse `html` with the row selector and return one normalized dict per row.

    The returned dicts use the same keys as `NormalizedJob` (minus experience
    parsing, which the adapter does once); `apply_url` is made absolute.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, str | None]] = []
    for el in soup.select(spec["list_item"]):
        title = extract_one(el, spec["title"])
        apply_url = extract_one(el, spec["apply_url"])
        if not title or not apply_url:
            continue
        if apply_url.startswith("/") or not apply_url.startswith(("http://", "https://")):
            apply_url = urljoin(base_url, apply_url)
        detail_link = extract_one(el, spec.get("detail_link"))
        if detail_link and (detail_link.startswith("/") or not detail_link.startswith(("http://", "https://"))):
            detail_link = urljoin(base_url, detail_link)
        rows.append({
            "title": title,
            "apply_url": apply_url,
            "location": extract_one(el, spec.get("location")),
            "department": extract_one(el, spec.get("department")),
            "employment_type": extract_one(el, spec.get("employment_type")),
            "posted_date": extract_one(el, spec.get("posted_date")),
            "description": extract_one(el, spec.get("description")),
            "detail_link": detail_link,
        })
    return rows


def extract_description_from_detail(html: str, sel: str | None) -> str | None:
    if not sel:
        return None
    soup = BeautifulSoup(html, "html.parser")
    return extract_one(soup, sel)
