"""Tests for scripts/heal_seeds.py — candidate generation, the name-vs-content
collision guard, the sequential verification flow, and the atomic seed write.

All live probing is respx-mocked; no network is touched.
"""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from backend.detect import detect_ats
from scripts.heal_seeds import (
    _atomic_write_json,
    _verify,
    canonical_url,
    distinctive_tokens,
    identifier_candidates,
    name_verdict,
    workday_candidates,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_identifier_candidates_dedup_and_order():
    cands = identifier_candidates("Acme Corp", "acmecorp")
    assert cands[0] == "acmecorp"  # current first
    assert "acmecorp" in cands and "acme-corp" in cands
    # no duplicates
    assert len(cands) == len(set(cands))


def test_canonical_url_matches_detect_ats():
    # Each canonical URL must classify back to its own family.
    for family, ident in [
        ("greenhouse", "stripe"),
        ("lever", "netflix"),
        ("ashby", "openai"),
        ("smartrecruiters", "Visa"),
        ("workable", "toast"),
        ("recruitee", "mollie"),
        ("teamtailor", "spotify"),
    ]:
        url = canonical_url(family, ident)
        detected, _ = detect_ats(url)
        assert detected == family, f"{family}: {url} detected as {detected}"


def test_canonical_url_workday_detects():
    url = canonical_url("workday", "nvidia.wd5.myworkdayjobs.com|nvidia|NVIDIAExternalCareerSite")
    detected, _ = detect_ats(url)
    assert detected == "workday"


def test_distinctive_tokens_drops_short_and_generic():
    assert distinctive_tokens("Box") == set()          # too short
    assert distinctive_tokens("AI Labs") == set()       # all generic/short
    assert "notion" in distinctive_tokens("Notion")
    assert "wealthsimple" in distinctive_tokens("Wealthsimple Inc")
    assert "inc" not in distinctive_tokens("Wealthsimple Inc")


@pytest.mark.parametrize(
    "name,employer,expected",
    [
        ("Acme Corp", "acme technologies", "match"),
        ("Acme", "", "unverified"),
        ("Box", "anything at all", "weak"),
        ("Acme", "Globex Industries", "mismatch"),
    ],
)
def test_name_verdict(name, employer, expected):
    assert name_verdict(name, employer) == expected


def test_workday_candidates_varies_pod():
    cands = workday_candidates("nvidia.wd5.myworkdayjobs.com|nvidia|Site")
    assert "nvidia.wd5.myworkdayjobs.com|nvidia|Site" not in cands  # current excluded
    assert "nvidia.wd1.myworkdayjobs.com|nvidia|Site" in cands
    assert all(c.endswith("|nvidia|Site") for c in cands)


def test_workday_candidates_empty_for_malformed():
    assert workday_candidates(None) == []
    assert workday_candidates("not-three-parts") == []


# ---------------------------------------------------------------------------
# _verify flow (respx-mocked)
# ---------------------------------------------------------------------------

_GH_JOBS = {"jobs": [{"id": 1, "title": "Engineer", "absolute_url": "https://x/1"}]}
_LV_URL = "https://api.lever.co/v0/postings/oldslug?mode=json"
_GH_JOBS_URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
_GH_BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/acme"


async def _run_verify(name: str, board_name: str, old_works: bool):
    async with httpx.AsyncClient() as client:
        with respx.mock(assert_all_called=False) as router:
            router.get(_LV_URL).mock(
                return_value=httpx.Response(200, json=[{"id": "a", "text": "Old",
                                                        "hostedUrl": "https://x/a"}])
                if old_works else httpx.Response(404, text="gone")
            )
            router.get(_GH_JOBS_URL).mock(return_value=httpx.Response(200, json=_GH_JOBS))
            router.get(_GH_BOARD_URL).mock(
                return_value=httpx.Response(200, json={"name": board_name})
            )
            res = {
                "name": name, "status": "candidate",
                "old": ("lever", "oldslug"), "new": ("greenhouse", "acme"),
            }
            return await _verify(client, res)


async def test_verify_keeps_when_old_still_works():
    res = await _run_verify("Acme", "Acme", old_works=True)
    assert res["status"] == "ok"  # old config recovered -> no re-point


async def test_verify_applies_fix_when_employer_matches():
    res = await _run_verify("Acme", "Acme Corporation", old_works=False)
    assert res["status"] == "fixed"
    assert res["new"] == ("greenhouse", "acme")


async def test_verify_needs_review_on_employer_mismatch():
    res = await _run_verify("Acme", "Globex Industries", old_works=False)
    assert res["status"] == "needs_review"
    assert res["verdict"] == "mismatch"


async def test_verify_needs_review_on_weak_name():
    # "Box" has no distinctive token -> never auto-applied even if a board matches.
    res = await _run_verify("Box", "Box Inc", old_works=False)
    assert res["status"] == "needs_review"
    assert res["verdict"] == "weak"


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


def test_atomic_write_json(tmp_path):
    target = tmp_path / "companies.json"
    data = [{"name": "A", "ats_type": "greenhouse"}]
    _atomic_write_json(target, data)
    assert json.loads(target.read_text(encoding="utf-8")) == data
    # no leftover temp file
    assert not (tmp_path / "companies.json.tmp").exists()
    assert list(tmp_path.iterdir()) == [target]
