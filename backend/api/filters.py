"""Job query builder.

`build_jobs_query()` returns a SQLAlchemy `Select` honoring every filter the
dashboard exposes. Keyword matching uses FTS5 for tokenizable terms
(`^[\\w-]+$`) and `LIKE` for terms with punctuation (e.g. `c++`, `c#`, `.net`)
so the spec's stated keywords all work without surprises.

Cursor pagination is keyset-based on `(sort_key, id)` — opaque base64 cursor
so clients can't poke at it.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import Select, and_, func, literal, or_, select, text
from sqlalchemy.orm import Session, aliased

from ..models import Company, Job


SAFE_TOKEN_RE = re.compile(r"^[\w\-]+$", re.UNICODE)


# ---------------------------------------------------------------------------
# Filter params (server-side)
# ---------------------------------------------------------------------------


@dataclass
class JobFilters:
    company_ids: list[int] | None = None  # None == "all"
    keywords: list[str] | None = None
    keyword_logic: str = "or"  # "and" | "or"
    experience_min: int | None = None
    experience_max: int | None = None
    posted_within_days: int = 15  # capped at 15
    location: str | None = None
    remote_only: bool | None = None
    sort: str = "posted_date"  # "posted_date" | "company" | "title" | "first_seen"
    new_since: datetime | None = None
    new_in_last_run: bool = False
    active_only: bool = True


# ---------------------------------------------------------------------------
# FTS5 / LIKE keyword splitting
# ---------------------------------------------------------------------------


def _split_keywords(keywords: Sequence[str]) -> tuple[list[str], list[str]]:
    """Partition keywords into (fts_tokens, like_terms).

    A keyword is FTS5-safe iff it's a single bare word (letters/digits/_/-).
    Anything else (c++, c#, .net, "machine learning") falls back to LIKE so
    spec-listed examples don't silently match nothing.
    """
    fts, like = [], []
    for k in keywords:
        k = k.strip()
        if not k:
            continue
        if SAFE_TOKEN_RE.match(k) and " " not in k:
            fts.append(k)
        else:
            like.append(k)
    return fts, like


def _build_fts_match_expr(fts_tokens: list[str], logic: str) -> str:
    """Compose an FTS5 MATCH query string from already-validated tokens."""
    op = " AND " if logic == "and" else " OR "
    # Tokens are already validated to `^[\\w-]+$`, so this is injection-safe.
    return op.join(fts_tokens)


# ---------------------------------------------------------------------------
# Cursor (opaque base64 of "sort_value|id")
# ---------------------------------------------------------------------------


def encode_cursor(sort_value, job_id: int) -> str:
    if isinstance(sort_value, datetime):
        sv = sort_value.isoformat()
    elif sort_value is None:
        sv = ""
    else:
        sv = str(sort_value)
    raw = f"{sv}|{job_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, int]:
    pad = "=" * (-len(cursor) % 4)
    raw = base64.urlsafe_b64decode(cursor + pad).decode("utf-8")
    sv, _, job_id_str = raw.rpartition("|")
    return sv, int(job_id_str)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_jobs_query(filters: JobFilters, cursor: str | None = None) -> Select:
    """Compose the SELECT used by `/jobs` and `/jobs/export.csv`.

    Returns a `Select` over (Job, Company.name). The caller adds `.limit()`.
    """
    stmt: Select = select(Job, Company.name.label("company_name")).join(
        Company, Company.id == Job.company_id
    )

    if filters.active_only:
        stmt = stmt.where(Job.is_active.is_(True))

    # posted_within_days (capped at 15 per spec §5 schema)
    days = min(max(filters.posted_within_days, 1), 15)
    cutoff = datetime.utcnow() - timedelta(days=days)
    stmt = stmt.where(or_(Job.posted_date.is_(None), Job.posted_date >= cutoff))

    if filters.company_ids:
        stmt = stmt.where(Job.company_id.in_(filters.company_ids))

    if filters.experience_min is not None:
        # Job's max (or min if max is null) must be >= filter's min.
        stmt = stmt.where(
            or_(
                Job.experience_max >= filters.experience_min,
                and_(Job.experience_max.is_(None), Job.experience_min >= filters.experience_min),
                # Jobs with no parsed experience pass through — better to show
                # than to hide silently. Comment out the next line to make the
                # filter strict.
                and_(Job.experience_min.is_(None), Job.experience_max.is_(None)),
            )
        )

    if filters.experience_max is not None:
        stmt = stmt.where(
            or_(
                Job.experience_min <= filters.experience_max,
                and_(Job.experience_min.is_(None), Job.experience_max <= filters.experience_max),
                and_(Job.experience_min.is_(None), Job.experience_max.is_(None)),
            )
        )

    if filters.location:
        loc_pat = f"%{filters.location.strip().lower()}%"
        stmt = stmt.where(func.lower(Job.location).like(loc_pat))

    if filters.remote_only:
        stmt = stmt.where(Job.remote_type == "remote")

    # ---- Keyword matching (FTS5 + LIKE hybrid) ----------------------------
    if filters.keywords:
        fts_tokens, like_terms = _split_keywords(filters.keywords)
        logic = filters.keyword_logic if filters.keyword_logic in {"and", "or"} else "or"

        clauses = []
        if fts_tokens:
            match_expr = _build_fts_match_expr(fts_tokens, logic)
            # rowid of jobs_fts == jobs.id (external-content table).
            fts_sub = (
                select(text("rowid"))
                .select_from(text("jobs_fts"))
                .where(text("jobs_fts MATCH :match_expr"))
                .params(match_expr=match_expr)
                .scalar_subquery()
            )
            clauses.append(Job.id.in_(fts_sub))

        for term in like_terms:
            pat = f"%{term.lower()}%"
            clauses.append(
                or_(
                    func.lower(Job.title).like(pat),
                    func.lower(func.coalesce(Job.description, "")).like(pat),
                )
            )

        if clauses:
            stmt = stmt.where(or_(*clauses) if logic == "or" else and_(*clauses))

    # ---- Newness toggles --------------------------------------------------
    if filters.new_since is not None:
        stmt = stmt.where(Job.first_seen_at >= filters.new_since)

    if filters.new_in_last_run:
        # Jobs whose first_seen_at falls within the most recent scrape run.
        # We use a scalar subquery so the caller doesn't need to pre-fetch it.
        from ..models import ScrapeRun

        last_started = (
            select(func.max(ScrapeRun.started_at)).scalar_subquery()
        )
        stmt = stmt.where(Job.first_seen_at >= last_started)

    # ---- Sort + cursor ----------------------------------------------------
    sort = filters.sort if filters.sort in {"posted_date", "company", "title", "first_seen"} else "posted_date"

    if sort == "posted_date":
        sort_col = Job.posted_date
        order = [Job.posted_date.desc().nullslast(), Job.id.desc()]
    elif sort == "first_seen":
        sort_col = Job.first_seen_at
        order = [Job.first_seen_at.desc(), Job.id.desc()]
    elif sort == "company":
        sort_col = Company.name
        order = [Company.name.asc(), Job.id.desc()]
    else:  # title
        sort_col = Job.title
        order = [Job.title.asc(), Job.id.desc()]

    if cursor:
        try:
            sv, last_id = decode_cursor(cursor)
        except (ValueError, base64.binascii.Error):
            raise ValueError(f"invalid cursor: {cursor!r}")

        if sort in {"posted_date", "first_seen"}:
            # Descending: take rows strictly before (sv, last_id).
            cursor_dt = datetime.fromisoformat(sv) if sv else None
            if cursor_dt is None:
                # NULLs go last in desc nullslast; once we're past them, only
                # `id < last_id AND sort_col IS NULL` can follow.
                stmt = stmt.where(and_(sort_col.is_(None), Job.id < last_id))
            else:
                stmt = stmt.where(
                    or_(
                        sort_col < cursor_dt,
                        and_(sort_col == cursor_dt, Job.id < last_id),
                        # NULL sort values come after non-null in desc nullslast.
                        sort_col.is_(None),
                    )
                )
        else:
            # Ascending string sort.
            stmt = stmt.where(
                or_(
                    sort_col > sv,
                    and_(sort_col == sv, Job.id < last_id),
                )
            )

    return stmt.order_by(*order)


def cursor_for_row(filters: JobFilters, job: Job, company_name: str) -> str:
    sort = filters.sort
    if sort == "posted_date":
        return encode_cursor(job.posted_date, job.id)
    if sort == "first_seen":
        return encode_cursor(job.first_seen_at, job.id)
    if sort == "company":
        return encode_cursor(company_name, job.id)
    return encode_cursor(job.title, job.id)


# ---------------------------------------------------------------------------
# Keyword matching for response decoration
# ---------------------------------------------------------------------------


def matched_keywords(job: Job, keywords: Sequence[str] | None) -> list[str]:
    """Cheap client-side highlight: which of the requested keywords appear
    in this job's title or description? Used to populate `keywords_matched`
    for the dashboard's chip UI without leaking the FTS internals.
    """
    if not keywords:
        return []
    hay = " ".join([job.title or "", job.description or ""]).lower()
    return [k for k in keywords if k and k.lower() in hay]
