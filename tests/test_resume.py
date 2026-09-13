"""Tests for the BM25 scorer + the /api/v1/resume endpoints + sort=match."""
from __future__ import annotations

import time

import pytest

from backend.resume import (
    bag_of_words,
    score_documents,
    tokenize,
)


# ---------------------------------------------------------------------------
# Pure-function tests (no DB)
# ---------------------------------------------------------------------------


def test_tokenize_preserves_tech_tokens():
    toks = tokenize("Skilled in C++, C#, .NET, and Node.js")
    assert "c++" in toks
    assert "c#" in toks
    assert ".net" in toks
    assert "node.js" in toks


def test_tokenize_lowercases_and_drops_stops():
    toks = tokenize("The QUICK BROWN fox JUMPED over THE lazy dog")
    assert "the" not in toks
    assert "over" not in toks
    assert "quick" in toks
    assert "brown" in toks


def test_bag_of_words_counts():
    bag = bag_of_words("python python python kubernetes")
    assert bag["python"] == 3
    assert bag["kubernetes"] == 1


def test_score_documents_ranks_by_overlap():
    resume = bag_of_words(
        "Python engineer with FastAPI, PostgreSQL, and Kubernetes experience"
    )
    docs = [
        (1, "Senior Python Engineer — build FastAPI backends with PostgreSQL"),
        (2, "Marketing coordinator — email campaigns, content strategy"),
        (3, "Kubernetes SRE — Terraform, Prometheus, Python"),
        (4, "COBOL mainframe developer — CICS, DB2"),
    ]
    scored = {s.job_id: s for s in score_documents(resume, docs)}
    # Highest-signal JD (multiple overlaps + Kubernetes) should top the list.
    ranked = sorted(scored.values(), key=lambda s: s.score, reverse=True)
    assert ranked[0].job_id in {1, 3}
    # Marketing + COBOL should be zero (no overlap after stop-word removal).
    assert scored[2].score == 0.0
    assert scored[4].score == 0.0
    # Matched-terms surface — Python job should list python + fastapi.
    py_terms = set(scored[1].matched_terms)
    assert "python" in py_terms
    assert "fastapi" in py_terms


def test_score_documents_empty_resume_returns_zeros():
    scored = score_documents({}, [(1, "some text"), (2, "other text")])
    assert all(s.score == 0.0 for s in scored)


# ---------------------------------------------------------------------------
# API-integration tests
# ---------------------------------------------------------------------------


def _upload_resume(client, text: str) -> dict:
    r = client.post("/api/v1/resume", json={"text": text, "name": "test"})
    assert r.status_code == 201, r.text
    return r.json()


def _wait_for_scoring(client, timeout: float = 5.0) -> dict:
    """Background rescoring runs on FastAPI's BackgroundTasks. Poll until it
    lands or fail loudly."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get("/api/v1/resume").json()
        if body and body.get("scored_at"):
            return body
        time.sleep(0.05)
    raise AssertionError("scoring did not finish within timeout")


def test_upload_and_score_flow(seeded_db):
    client, _ = seeded_db
    _upload_resume(client, "Python engineer with FastAPI PostgreSQL Kubernetes")
    body = _wait_for_scoring(client)
    assert body["matches_total"] >= 1
    assert body["matches_nonzero"] >= 1


def test_sort_match_orders_by_score(seeded_db):
    client, _ = seeded_db
    _upload_resume(
        client,
        "Python engineer with FastAPI, PostgreSQL, C++ systems and Kubernetes experience",
    )
    _wait_for_scoring(client)
    body = client.get(
        "/api/v1/jobs",
        params={"sort": "match", "include_total": True, "limit": 10},
    ).json()
    items = body["items"]
    assert len(items) >= 3
    # Every returned row must carry a match_score field.
    for it in items:
        assert "match_score" in it
    # Sorted desc.
    scores = [it.get("match_score") or 0 for it in items]
    assert scores == sorted(scores, reverse=True)
    # At least one non-trivial match.
    assert scores[0] > 0
    # Top result should overlap with resume terms.
    assert any(
        t in items[0]["matched_terms"] for t in ("python", "fastapi", "kubernetes", "c++")
    )


def test_delete_resume_and_sort_match_fallback(seeded_db):
    client, _ = seeded_db
    _upload_resume(client, "Python engineer FastAPI Kubernetes")
    _wait_for_scoring(client)

    resp = client.delete("/api/v1/resume")
    assert resp.status_code == 204
    assert client.get("/api/v1/resume").json() is None

    # sort=match without an active resume silently falls back to posted_date
    # — the endpoint returns rows, none carry a score.
    body = client.get("/api/v1/jobs", params={"sort": "match"}).json()
    assert len(body["items"]) > 0
    assert all(it.get("match_score") is None for it in body["items"])


def test_rescore_endpoint(seeded_db):
    client, _ = seeded_db
    _upload_resume(client, "Python engineer FastAPI Kubernetes PostgreSQL")
    _wait_for_scoring(client)
    r = client.post("/api/v1/resume/rescore")
    assert r.status_code == 200
    # Rescore returns the placeholder shape; the actual re-fill runs in a
    # background task, and the subsequent GET should still show a scored_at.
    _wait_for_scoring(client)
    body = client.get("/api/v1/resume").json()
    assert body["scored_at"] is not None


def test_rescore_without_resume_404(seeded_db):
    client, _ = seeded_db
    r = client.post("/api/v1/resume/rescore")
    assert r.status_code == 404


def test_short_resume_rejected(seeded_db):
    client, _ = seeded_db
    r = client.post("/api/v1/resume", json={"text": "too short"})
    assert r.status_code == 422


@pytest.mark.parametrize("path", ["/api/v1/resume", "/api/v1/resume/rescore"])
def test_mutating_endpoints_require_api_key_when_configured(seeded_db, monkeypatch, path):
    import dataclasses

    from backend import config
    import backend.api.deps as deps_mod

    client, settings_ = seeded_db
    new = dataclasses.replace(settings_, api_key="secret")
    monkeypatch.setattr(config, "settings", new)
    monkeypatch.setattr(deps_mod, "settings", new)

    if path.endswith("rescore"):
        r = client.post(path)
    else:
        r = client.post(path, json={"text": "python fastapi kubernetes engineer"})
    assert r.status_code == 401
