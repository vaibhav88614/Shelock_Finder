"""Tests for `detect_ats(url)`."""
from __future__ import annotations

import pytest

from backend.detect import detect_ats


@pytest.mark.parametrize("url, expected", [
    ("https://boards.greenhouse.io/stripe", ("greenhouse", "stripe")),
    ("https://boards.greenhouse.io/stripe/jobs/12345", ("greenhouse", "stripe")),
    ("https://job-boards.greenhouse.io/discord", ("greenhouse", "discord")),
    ("https://jobs.lever.co/netflix", ("lever", "netflix")),
    ("https://jobs.lever.co/netflix/abc-1234/apply", ("lever", "netflix")),
    ("https://jobs.smartrecruiters.com/Box", ("smartrecruiters", "Box")),
    ("https://careers.smartrecruiters.com/atlassian", ("smartrecruiters", "atlassian")),
    ("https://jobs.ashbyhq.com/linear", ("ashby", "linear")),
    ("https://apply.workable.com/lyft", ("workable", "lyft")),
    ("https://monday.recruitee.com/", ("recruitee", "monday")),
    ("https://acme.jobs.personio.de", ("personio", "acme")),
    ("https://acme.jobs.personio.com/", ("personio", "acme")),
    ("https://klarna.teamtailor.com/jobs", ("teamtailor", "klarna")),
    (
        "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/details/...",
        ("workday", "nvidia.wd5.myworkdayjobs.com|nvidia|NVIDIAExternalCareerSite"),
    ),
    (
        "https://google.wd1.myworkdayjobs.com/google/",
        ("workday", "google.wd1.myworkdayjobs.com|google|google"),
    ),
    # www-prefixed should still match.
    ("https://www.boards.greenhouse.io/segment", ("greenhouse", "segment")),
])
def test_detect_known_ats(url, expected):
    assert detect_ats(url) == expected


@pytest.mark.parametrize("url", [
    "https://example.com/careers",
    "https://acme.io/jobs",
    "https://random-startup.com/about",
    "",
    "not a url",
])
def test_detect_unknown_returns_none_tuple(url):
    assert detect_ats(url) == (None, None)
