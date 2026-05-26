"""Parse "years of experience" from free-form job description / title text.

The scraper calls `parse_experience(text) -> (min, max)` at ingest time so the
dashboard can filter without re-scanning descriptions on every request.

The parser is intentionally conservative: it returns `(None, None)` when no
clear signal is present rather than guessing. False positives are worse than
missing data because they would silently filter rows out of the dashboard.

Recognized patterns (case-insensitive, all return integer years):
    "3-5 years"                    -> (3, 5)
    "3 to 5 years"                 -> (3, 5)
    "3+ years"                     -> (3, None)
    "minimum 2 years"              -> (2, None)
    "at least 4 years"             -> (4, None)
    "5 or more years"              -> (5, None)
    "up to 7 years"                -> (None, 7)
    "2 years experience"           -> (2, 2)
    "two to four years"            -> ignored (no number-word support yet)
"""
from __future__ import annotations

import re

# Capture order matters: try ranges first, then "min/at least", then single.
_RANGE_RE = re.compile(
    r"(?P<min>\d{1,2})\s*(?:-|–|—|to)\s*(?P<max>\d{1,2})\+?\s*(?:\+)?\s*year",
    re.IGNORECASE,
)
_PLUS_RE = re.compile(
    r"(?:(?:min(?:imum)?|at\s+least|over)\s+)?(?P<min>\d{1,2})\s*\+\s*year",
    re.IGNORECASE,
)
_MIN_RE = re.compile(
    r"(?:min(?:imum)?|at\s+least|over)\s+(?P<min>\d{1,2})\s*year",
    re.IGNORECASE,
)
_OR_MORE_RE = re.compile(
    r"(?P<min>\d{1,2})\s+or\s+more\s+year",
    re.IGNORECASE,
)
_UP_TO_RE = re.compile(
    r"up\s+to\s+(?P<max>\d{1,2})\s*year",
    re.IGNORECASE,
)
_SINGLE_RE = re.compile(
    r"(?<!\d)(?P<n>\d{1,2})\s*year[s]?\s+(?:of\s+)?(?:professional\s+|relevant\s+|industry\s+)?experience",
    re.IGNORECASE,
)


def parse_experience(text: str | None) -> tuple[int | None, int | None]:
    """Return (experience_min, experience_max) parsed from free text.

    Both values are years (integers, 0-30). Either may be None.
    """
    if not text:
        return (None, None)

    m = _RANGE_RE.search(text)
    if m:
        lo = int(m.group("min"))
        hi = int(m.group("max"))
        if 0 <= lo <= hi <= 30:
            return (lo, hi)

    m = _PLUS_RE.search(text)
    if m:
        lo = int(m.group("min"))
        if 0 <= lo <= 30:
            return (lo, None)

    m = _OR_MORE_RE.search(text)
    if m:
        lo = int(m.group("min"))
        if 0 <= lo <= 30:
            return (lo, None)

    m = _MIN_RE.search(text)
    if m:
        lo = int(m.group("min"))
        if 0 <= lo <= 30:
            return (lo, None)

    m = _UP_TO_RE.search(text)
    if m:
        hi = int(m.group("max"))
        if 0 <= hi <= 30:
            return (None, hi)

    m = _SINGLE_RE.search(text)
    if m:
        n = int(m.group("n"))
        if 0 <= n <= 30:
            return (n, n)

    return (None, None)
