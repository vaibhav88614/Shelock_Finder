"""URL-pattern based ATS detection.

`detect_ats(url)` looks at the host + path of a careers URL and, when it
matches a known ATS pattern, returns the `(ats_type, ats_identifier)` tuple
the scrape orchestrator needs. Falls back to `(None, None)` so the caller can
default to `"custom"` and prompt the user for selectors.

We deliberately avoid HTTP probes here — detection is pure-function and runs
in the request handler for `POST /api/v1/companies`. The probe path (head
request, sniffing for JSON shape) belongs to a future phase if needed.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse


# Ordered list of (description, regex, callable(re.Match) -> (ats_type, identifier|None))
# First match wins. The regex is applied against `netloc + path`. The host
# portion is pre-lowercased but the path is preserved as-is so case-sensitive
# identifiers (e.g. SmartRecruiters "Box", Workday "NVIDIAExternalCareerSite")
# survive intact. All regexes carry IGNORECASE for the path portion.
_RULES: list[tuple[str, re.Pattern[str], callable]] = [
    # Greenhouse
    (
        "greenhouse hosted board",
        re.compile(r"^boards\.greenhouse\.io/(?P<id>[a-z0-9._-]+)", re.IGNORECASE),
        lambda m: ("greenhouse", m.group("id").lower()),
    ),
    (
        "greenhouse job-boards subdomain",
        re.compile(r"^job-boards\.greenhouse\.io/(?P<id>[a-z0-9._-]+)", re.IGNORECASE),
        lambda m: ("greenhouse", m.group("id").lower()),
    ),
    # Lever
    (
        "lever hosted board",
        re.compile(r"^jobs\.lever\.co/(?P<id>[a-z0-9._-]+)", re.IGNORECASE),
        lambda m: ("lever", m.group("id").lower()),
    ),
    # SmartRecruiters (case-preserving identifier)
    (
        "smartrecruiters hosted",
        re.compile(r"^(?:jobs|careers)\.smartrecruiters\.com/(?P<id>[A-Za-z0-9._-]+)"),
        lambda m: ("smartrecruiters", m.group("id")),
    ),
    # Ashby
    (
        "ashby hosted",
        re.compile(r"^jobs\.ashbyhq\.com/(?P<id>[a-z0-9._-]+)", re.IGNORECASE),
        lambda m: ("ashby", m.group("id").lower()),
    ),
    # Workable
    (
        "workable hosted",
        re.compile(r"^apply\.workable\.com/(?P<id>[a-z0-9._-]+)", re.IGNORECASE),
        lambda m: ("workable", m.group("id").lower()),
    ),
    (
        "workable subdomain",
        re.compile(r"^(?P<id>[a-z0-9-]+)\.workable\.com(?:/|$)"),
        lambda m: ("workable", m.group("id")),
    ),
    # Recruitee
    (
        "recruitee subdomain",
        re.compile(r"^(?P<id>[a-z0-9-]+)\.recruitee\.com(?:/|$)"),
        lambda m: ("recruitee", m.group("id")),
    ),
    # Personio
    (
        "personio subdomain",
        re.compile(r"^(?P<id>[a-z0-9-]+)\.jobs\.personio\.(?:de|com)(?:/|$)"),
        lambda m: ("personio", m.group("id")),
    ),
    # Teamtailor
    (
        "teamtailor subdomain",
        re.compile(r"^(?P<id>[a-z0-9-]+)\.teamtailor\.com(?:/|$)"),
        lambda m: ("teamtailor", m.group("id")),
    ),
    # Workday — host carries tenant, path carries the site name.
    #   https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/...
    (
        "workday hosted",
        re.compile(
            r"^(?P<host>(?P<tenant>[a-z0-9-]+)\.(?:wd\d+\.)?myworkdayjobs\.com)"
            r"/(?P<path>[^?#]+)"
        ),
        lambda m: ("workday", _workday_identifier(m.group("host"), m.group("tenant"), m.group("path"))),
    ),
]


_LOCALE_RE = re.compile(r"^[a-z]{2}(?:[-_][a-z]{2})?$", re.IGNORECASE)


def _workday_identifier(host: str, tenant: str, path: str) -> str | None:
    segments = [s for s in path.split("/") if s and not _LOCALE_RE.match(s)]
    if not segments:
        return None
    site = segments[0]
    return f"{host}|{tenant}|{site}"


def detect_ats(url: str) -> tuple[str | None, str | None]:
    """Inspect `url` and return `(ats_type, ats_identifier)` if recognised.

    Returns `(None, None)` for unknown URLs so the caller can store the
    company as `ats_type="custom"` and prompt for selectors later.
    """
    if not url:
        return (None, None)
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
    except ValueError:
        return (None, None)
    host = (parsed.netloc or "").lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path or "/"
    target = host + path
    for _name, pat, builder in _RULES:
        m = pat.search(target)
        if m:
            ats_type, identifier = builder(m)
            if ats_type and identifier:
                return (ats_type, identifier)
    return (None, None)
