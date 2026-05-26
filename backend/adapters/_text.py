"""Tiny shared helpers reused by multiple ATS adapters.

Kept dependency-free so HTML adapters (phase 6) can import without dragging
the JSON-API adapters in.
"""
from __future__ import annotations

import html as _html
import re


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")
_NEWLINES_RE = re.compile(r"\n{3,}")
_REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)
_HYBRID_RE = re.compile(r"\bhybrid\b", re.IGNORECASE)
_ONSITE_RE = re.compile(r"\b(on[- ]?site|in[- ]?office)\b", re.IGNORECASE)


def strip_html(s: str | None) -> str | None:
    """Strip HTML tags + unescape entities. Returns None for falsy input."""
    if not s:
        return None
    text = _TAG_RE.sub(" ", s)
    text = _html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = _NEWLINES_RE.sub("\n\n", text).strip()
    return text or None


def detect_remote_type(*candidates: str | None) -> str | None:
    """Sniff `remote|hybrid|onsite` from any number of free-text fields."""
    haystack = " ".join(c for c in candidates if c)[:4000]
    if not haystack:
        return None
    if _REMOTE_RE.search(haystack):
        return "remote"
    if _HYBRID_RE.search(haystack):
        return "hybrid"
    if _ONSITE_RE.search(haystack):
        return "onsite"
    return None
