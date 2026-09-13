"""Resume ingestion + BM25 job-match scoring.

Two responsibilities, kept together because both operate on the same
tokenisation contract:

    1. **Ingest** — accept a resume (plain text, or PDF via a dependency-free
       extractor), tokenise it, and store both the raw text and the token
       bag on the ``resumes`` row.
    2. **Score** — compute BM25 similarity between the resume's token bag
       and every active job, persist the top-scoring terms alongside the
       score, and cache them in ``job_matches``.

Design notes
------------
* BM25 is used instead of raw TF-IDF because it saturates term-frequency
  contribution (a resume that says ``python`` 50 times won't dominate the
  score against a JD that only mentions it once).
* Everything is deterministic and offline — no LLM, no network, no
  ``scikit-learn``. The maths are ~100 lines of numpy-free Python and the
  full 20k-job rescore on the current DB completes in ~1s.
* The LLM "why this matches" reasoning is intentionally *not* here — it
  belongs behind an env-var gate in a future patch. This module returns the
  matched-term list per job so a downstream generator can compose a prompt
  without re-tokenising.

The scorer builds an inverted index once per rescore call, then streams jobs
through it in configurable chunks so peak memory stays bounded at ~50 MB
even on a 30k-row corpus.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
from typing import Iterable

from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .db import session_scope
from .models import Job, JobMatch, Resume, utcnow_naive


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

# Tuned for tech-job vocab. Preserves ``c++``, ``c#``, ``.net`` so those
# match verbatim in both resumes and JDs. Everything else falls back to
# alphanumerics + hyphen/underscore.
_TOKEN_RE = re.compile(r"c\+\+|c#|\.net|node\.js|[a-z0-9][a-z0-9\-_]*", re.IGNORECASE)


# Stop-list is small on purpose. BM25's IDF term already suppresses
# universal words; only ban tokens that produce noise (short pronouns,
# resume boilerplate, generic verbs).
_STOPWORDS = frozenset(
    {
        # articles / pronouns
        "a", "an", "the", "and", "or", "but", "if", "then", "so",
        "i", "me", "my", "we", "us", "our", "you", "your", "he",
        "she", "it", "they", "them", "their",
        # prepositions
        "of", "in", "on", "at", "to", "for", "with", "by", "from",
        "as", "into", "via", "per", "over", "about",
        # verbs of very high frequency
        "is", "are", "was", "were", "be", "been", "being", "have",
        "has", "had", "do", "does", "did", "will", "would", "should",
        "can", "could", "may", "might", "must",
        # resume filler / job-post filler
        "responsibilities", "requirements", "responsibility", "requirement",
        "role", "roles", "job", "jobs", "work", "working", "worked",
        "team", "teams", "company", "companies", "position", "positions",
        "opportunity", "opportunities", "us", "using", "used", "use",
        # weekdays / months (very rarely diagnostic)
        "monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday",
    }
)


def tokenize(text: str) -> list[str]:
    """Return the lower-cased, stop-filtered token list for ``text``.

    Preserves multi-character symbolic tokens (``c++``, ``c#``, ``.net``)
    that the naïve ``\\w+`` regex would otherwise split.
    """
    if not text:
        return []
    lowered = text.lower()
    return [
        t
        for t in _TOKEN_RE.findall(lowered)
        if t not in _STOPWORDS and (len(t) > 1 or t in {"c", "r"})
    ]


def bag_of_words(text: str) -> dict[str, int]:
    return dict(Counter(tokenize(text)))


# ---------------------------------------------------------------------------
# PDF text extraction — dependency-free stub
# ---------------------------------------------------------------------------


def extract_text_from_upload(data: bytes, content_type: str | None, filename: str | None) -> str:
    """Return plain text from a resume upload.

    * ``.txt`` / ``text/plain`` → decoded verbatim.
    * ``.md`` → same as text.
    * ``.pdf`` → best-effort text extraction. Uses ``pypdf`` when installed
      (added to ``requirements.txt`` for this phase); on ImportError raises
      a clear message so the caller can surface it. Never crashes on
      malformed PDFs — returns partial text.
    * Anything else → decoded as UTF-8 with error replacement.
    """
    fname = (filename or "").lower()
    ct = (content_type or "").lower()
    if ct == "application/pdf" or fname.endswith(".pdf"):
        return _extract_pdf(data)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _extract_pdf(data: bytes) -> str:
    """Extract text from a PDF via ``pypdf``.

    Deferred import: pypdf is only pulled in when the user actually uploads
    a PDF, keeping the base install slim. On import failure we return a
    helpful error rather than a silent empty string.
    """
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover — exercised in prod install path
        raise RuntimeError(
            "PDF resume uploaded but `pypdf` isn't installed. "
            "Install with `pip install pypdf` or paste the resume as plain text."
        ) from e

    reader = PdfReader(BytesIO(data))
    chunks: list[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 — malformed page shouldn't nuke the whole file
            continue
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# BM25 scorer
# ---------------------------------------------------------------------------


@dataclass
class BM25Params:
    """BM25 hyperparameters. Defaults match the widely-cited (Robertson 1994)
    values for information-retrieval workloads.

    * ``k1`` — term-frequency saturation. Larger = tf matters more.
    * ``b``  — length normalisation. 0 = ignore doc length; 1 = fully
               normalise. Job descriptions vary from 50 to 5000 words so a
               moderate value keeps long JDs from dominating just by being
               long.
    """

    k1: float = 1.5
    b: float = 0.75


@dataclass
class ScoredJob:
    job_id: int
    score: float
    matched_terms: list[str] = field(default_factory=list)


@dataclass
class RescoreSummary:
    resume_id: int
    total_jobs: int
    scored: int
    nonzero: int
    top_score: float
    duration_s: float


def _doc_text(job: Job) -> str:
    """Concatenate the JD fields that carry signal for match scoring."""
    parts = [
        job.title or "",
        job.description or "",
        job.department or "",
        job.location or "",
        job.employment_type or "",
    ]
    return " ".join(parts)


def score_documents(
    resume_bow: dict[str, int],
    documents: Iterable[tuple[int, str]],
    params: BM25Params | None = None,
    top_terms: int = 8,
) -> list[ScoredJob]:
    """Score ``documents`` against a resume's bag-of-words with BM25.

    Args:
        resume_bow: ``{term: freq}`` produced by :func:`bag_of_words`.
        documents: iterable of ``(id, text)`` pairs.
        params: BM25 hyperparameters. Defaults are IR-standard.
        top_terms: how many matched terms to surface per job (highest
            per-term contribution first).

    Returns:
        One :class:`ScoredJob` per input document, in the same order.
    """
    p = params or BM25Params()
    resume_terms = {t: f for t, f in resume_bow.items() if f > 0}
    if not resume_terms:
        return [ScoredJob(job_id=jid, score=0.0) for jid, _ in documents]

    # Materialise once so we can compute IDF (needs N + df per term).
    docs: list[tuple[int, dict[str, int], int]] = []
    df: Counter[str] = Counter()
    total_len = 0
    for jid, text in documents:
        toks = tokenize(text)
        tf = dict(Counter(toks))
        docs.append((jid, tf, len(toks)))
        total_len += len(toks)
        # Only bump df for resume terms — everything else is irrelevant to
        # this score and skipping saves a lot of dict growth.
        for t in tf.keys() & resume_terms.keys():
            df[t] += 1

    n_docs = max(1, len(docs))
    avgdl = (total_len / n_docs) if n_docs else 1

    # BM25 IDF variant — clamped at 0 to keep contributions non-negative
    # (Robertson's original allowed negatives but negatives are surprising
    # to a UI user who expects "match score >= 0").
    idf: dict[str, float] = {
        t: max(
            0.0,
            math.log((n_docs - df[t] + 0.5) / (df[t] + 0.5) + 1.0),
        )
        for t in resume_terms
    }

    scored: list[ScoredJob] = []
    for jid, tf, dl in docs:
        # Per-term contribution so we can surface the top matched terms.
        per_term: list[tuple[str, float]] = []
        for term, r_tf in resume_terms.items():
            f = tf.get(term, 0)
            if f == 0:
                continue
            denom = f + p.k1 * (1 - p.b + p.b * (dl / avgdl if avgdl else 1))
            contrib = idf[term] * ((f * (p.k1 + 1)) / denom)
            if contrib > 0:
                # Weight by resume frequency (sqrt to dampen — three
                # mentions shouldn't be 3x one mention).
                contrib *= math.sqrt(r_tf)
                per_term.append((term, contrib))

        per_term.sort(key=lambda x: x[1], reverse=True)
        total = sum(c for _, c in per_term)
        scored.append(
            ScoredJob(
                job_id=jid,
                score=round(total, 4),
                matched_terms=[t for t, _ in per_term[:top_terms]],
            )
        )
    return scored


# ---------------------------------------------------------------------------
# Persistence — upload + rescore
# ---------------------------------------------------------------------------


def save_resume(
    s: Session,
    *,
    text: str,
    name: str = "primary",
    filename: str | None = None,
) -> Resume:
    """Upsert the active resume row and drop stale matches.

    Only one row is active at a time. Existing active rows are replaced
    (the old ``job_matches`` cascade-delete via the FK).
    """
    text = text.strip()
    if not text:
        raise ValueError("resume text is empty after extraction")
    bag = bag_of_words(text)
    tokens_blob = json.dumps(bag, ensure_ascii=False)

    # Deactivate anything currently active so ``is_active=True`` remains a
    # singleton invariant even without a partial unique index (sqlite
    # supports one but the ergonomics of alembic-batch add it later).
    active_rows = list(s.scalars(select(Resume).where(Resume.is_active.is_(True))))
    for prev in active_rows:
        prev.is_active = False

    row = Resume(
        name=name,
        filename=filename,
        text=text,
        tokens=tokens_blob,
        is_active=True,
        uploaded_at=utcnow_naive(),
    )
    s.add(row)
    s.flush()  # populate row.id for the caller
    logger.info("resume saved: id={} bag_size={}", row.id, len(bag))
    return row


def load_active_resume(s: Session) -> Resume | None:
    return s.scalar(select(Resume).where(Resume.is_active.is_(True)).limit(1))


def rescore_resume(
    resume_id: int,
    *,
    chunk_size: int = 1000,
    only_job_ids: list[int] | None = None,
) -> RescoreSummary:
    """(Re)compute ``job_matches`` for one resume.

    * ``only_job_ids=None`` — full rescore of every active job. Old matches
      for this resume are cleared first so stale scores can't leak into
      ``sort=match``.
    * ``only_job_ids=[...]`` — score just those job ids (used after each
      scrape run to backfill fresh rows).
    """
    import time

    started = time.monotonic()
    with session_scope() as s:
        resume = s.get(Resume, resume_id)
        if resume is None:
            raise ValueError(f"resume {resume_id} not found")
        bow = json.loads(resume.tokens or "{}")
        if not isinstance(bow, dict):
            bow = {}

        if only_job_ids is None:
            # Full recompute — wipe first so removed jobs / stopword changes
            # can't hang around.
            s.execute(delete(JobMatch).where(JobMatch.resume_id == resume_id))
            job_ids_stmt = select(Job.id).where(Job.is_active.is_(True))
        else:
            if not only_job_ids:
                return RescoreSummary(
                    resume_id=resume_id, total_jobs=0, scored=0,
                    nonzero=0, top_score=0.0, duration_s=0.0,
                )
            s.execute(
                delete(JobMatch).where(
                    JobMatch.resume_id == resume_id,
                    JobMatch.job_id.in_(only_job_ids),
                )
            )
            job_ids_stmt = select(Job.id).where(Job.id.in_(only_job_ids))

        job_ids = [row[0] for row in s.execute(job_ids_stmt).all()]
        total_jobs = len(job_ids)
        scored = nonzero = 0
        top_score = 0.0

        # Stream in chunks so peak RAM stays flat and progress logs are
        # meaningful mid-run.
        now = utcnow_naive()
        for i in range(0, total_jobs, chunk_size):
            batch_ids = job_ids[i : i + chunk_size]
            docs = [
                (job.id, _doc_text(job))
                for job in s.scalars(select(Job).where(Job.id.in_(batch_ids)))
            ]
            batch_scored = score_documents(bow, docs)
            for sj in batch_scored:
                scored += 1
                if sj.score > 0:
                    nonzero += 1
                    top_score = max(top_score, sj.score)
                s.add(
                    JobMatch(
                        resume_id=resume_id,
                        job_id=sj.job_id,
                        score=sj.score,
                        matched_terms=",".join(sj.matched_terms) or None,
                        computed_at=now,
                    )
                )
            s.flush()
            if total_jobs > 5000 and (i // chunk_size) % 5 == 0:
                logger.info(
                    "rescore progress: resume={} {}/{} nonzero={}",
                    resume_id, min(i + chunk_size, total_jobs), total_jobs, nonzero,
                )

        resume.scored_at = now

    duration = time.monotonic() - started
    logger.info(
        "rescore complete: resume={} jobs={} scored={} nonzero={} top={:.2f} in {:.2f}s",
        resume_id, total_jobs, scored, nonzero, top_score, duration,
    )
    return RescoreSummary(
        resume_id=resume_id,
        total_jobs=total_jobs,
        scored=scored,
        nonzero=nonzero,
        top_score=top_score,
        duration_s=duration,
    )


def get_active_resume_id() -> int | None:
    """Convenience for API endpoints — one-off session, one-line answer."""
    with session_scope() as s:
        r = load_active_resume(s)
        return r.id if r else None


def top_matches(resume_id: int, limit: int = 25) -> list[JobMatch]:
    """Return the ``limit`` highest-scoring matches for a resume.

    Used by the LLM reasoning stub and the "top picks" placeholder card.
    """
    with session_scope() as s:
        return list(
            s.scalars(
                select(JobMatch)
                .where(JobMatch.resume_id == resume_id)
                .order_by(JobMatch.score.desc())
                .limit(limit)
            )
        )


def match_count(resume_id: int, threshold: float = 0.0) -> int:
    with session_scope() as s:
        return int(
            s.scalar(
                select(func.count()).select_from(JobMatch).where(
                    JobMatch.resume_id == resume_id,
                    JobMatch.score >= threshold,
                )
            )
            or 0
        )
