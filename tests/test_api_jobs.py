"""Tests for /api/v1/jobs filters, FTS5, pagination, and CSV export."""
from __future__ import annotations

import csv
import io


# Total jobs visible by default (active=True, posted_date within 15d):
#  Stripe s1/s2/s3 + Netflix n1/n2/n3 = 6
# Excluded by default:
#  - OldCo o1 (is_active=False)
#  - OldCo o2 (posted 30d ago)
DEFAULT_TOTAL = 6


def _get_jobs(client, **params):
    resp = client.get("/api/v1/jobs", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_default_lists_only_active_recent(seeded_db):
    client, _ = seeded_db
    body = _get_jobs(client, include_total=True)
    assert body["total"] == DEFAULT_TOTAL
    titles = {j["title"] for j in body["items"]}
    assert "Stale Job" not in titles
    assert "Ancient Job" not in titles
    assert all(j["is_active"] for j in body["items"])


def test_filter_by_company_ids(seeded_db):
    client, _ = seeded_db
    # Get Stripe's id from /companies
    cos = client.get("/api/v1/companies").json()
    stripe_id = next(c["id"] for c in cos if c["name"] == "Stripe")
    body = _get_jobs(client, company_ids=[stripe_id])
    assert len(body["items"]) == 3
    assert {j["company_name"] for j in body["items"]} == {"Stripe"}


def test_keyword_fts_single_word(seeded_db):
    client, _ = seeded_db
    body = _get_jobs(client, keywords=["python"])
    titles = {j["title"] for j in body["items"]}
    # s1, s2, n2 mention python
    assert {"Senior Python Engineer", "Staff ML Engineer (Remote)", "Data Scientist"} <= titles


def test_keyword_like_handles_special_chars(seeded_db):
    """`c++` is not FTS5-tokenizable; the LIKE fallback must still find it."""
    client, _ = seeded_db
    body = _get_jobs(client, keywords=["c++"])
    titles = {j["title"] for j in body["items"]}
    assert titles == {"C++ Systems Engineer"}


def test_keyword_logic_and_vs_or(seeded_db):
    client, _ = seeded_db

    and_body = _get_jobs(client, keywords=["python", "react"], keyword_logic="and")
    or_body = _get_jobs(client, keywords=["python", "react"], keyword_logic="or")

    and_titles = {j["title"] for j in and_body["items"]}
    or_titles = {j["title"] for j in or_body["items"]}

    # No single posting mentions BOTH python and react.
    assert and_titles == set()
    # OR picks up python (3) + react (1) = 4 distinct titles.
    assert {"Senior Python Engineer", "Staff ML Engineer (Remote)",
            "Data Scientist", "Senior React Engineer"} == or_titles


def test_keyword_mixed_logic_with_special_char(seeded_db):
    """`python` (FTS) OR `c++` (LIKE) should match both groups."""
    client, _ = seeded_db
    body = _get_jobs(client, keywords=["python", "c++"], keyword_logic="or")
    titles = {j["title"] for j in body["items"]}
    assert "C++ Systems Engineer" in titles
    assert "Senior Python Engineer" in titles


def test_keywords_matched_chip_decoration(seeded_db):
    client, _ = seeded_db
    body = _get_jobs(client, keywords=["python", "ml"], keyword_logic="or")
    by_title = {j["title"]: j for j in body["items"]}
    py = by_title["Senior Python Engineer"]
    assert "python" in py["keywords_matched"]


def test_experience_filter(seeded_db):
    client, _ = seeded_db

    # Min 6 years: should include s2 (7) and overlap with s1 (5-8) and n1 (4-7).
    body = _get_jobs(client, experience_min=6)
    titles = {j["title"] for j in body["items"]}
    assert "Staff ML Engineer (Remote)" in titles
    assert "Senior Python Engineer" in titles  # 5-8 overlaps
    assert "Senior React Engineer" in titles   # 4-7 overlaps
    assert "Data Scientist" not in titles      # 3-5 doesn't reach 6
    assert "C++ Systems Engineer" not in titles  # 3-5 doesn't reach 6


def test_remote_only(seeded_db):
    client, _ = seeded_db
    body = _get_jobs(client, remote_only=True)
    titles = {j["title"] for j in body["items"]}
    assert titles == {"Staff ML Engineer (Remote)", "Data Scientist"}


def test_location_substring(seeded_db):
    client, _ = seeded_db
    body = _get_jobs(client, location="los gatos")
    titles = {j["title"] for j in body["items"]}
    assert titles == {"Senior React Engineer", "Junior Engineer (NEW)"}


def test_new_in_last_run_toggle(seeded_db):
    client, _ = seeded_db
    body = _get_jobs(client, new_in_last_run=True)
    titles = [j["title"] for j in body["items"]]
    assert titles == ["Junior Engineer (NEW)"]


def test_cursor_pagination(seeded_db):
    client, _ = seeded_db
    page1 = _get_jobs(client, limit=2, sort="posted_date")
    assert len(page1["items"]) == 2
    assert page1["next_cursor"]

    page2 = _get_jobs(client, limit=2, sort="posted_date", cursor=page1["next_cursor"])
    assert len(page2["items"]) == 2

    p1_ids = {j["id"] for j in page1["items"]}
    p2_ids = {j["id"] for j in page2["items"]}
    assert p1_ids.isdisjoint(p2_ids)

    # Walk to end
    seen = list(p1_ids | p2_ids)
    cursor = page2["next_cursor"]
    while cursor:
        body = _get_jobs(client, limit=2, sort="posted_date", cursor=cursor)
        for j in body["items"]:
            assert j["id"] not in seen
            seen.append(j["id"])
        cursor = body["next_cursor"]
    assert len(seen) == DEFAULT_TOTAL


def test_invalid_cursor_returns_400(seeded_db):
    client, _ = seeded_db
    resp = client.get("/api/v1/jobs", params={"cursor": "!!!not-base64!!!"})
    assert resp.status_code == 400


def test_get_one_job(seeded_db):
    client, _ = seeded_db
    listed = _get_jobs(client)["items"][0]
    detail = client.get(f"/api/v1/jobs/{listed['id']}").json()
    assert detail["id"] == listed["id"]
    assert detail["title"] == listed["title"]


def test_get_one_job_404(seeded_db):
    client, _ = seeded_db
    assert client.get("/api/v1/jobs/999999").status_code == 404


def test_export_csv_streams_filtered_rows(seeded_db):
    client, _ = seeded_db

    with client.stream("GET", "/api/v1/jobs/export.csv", params={"keywords": ["python"]}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers.get("content-disposition", "")
        body = b"".join(r.iter_bytes()).decode("utf-8")

    reader = csv.reader(io.StringIO(body))
    rows = list(reader)
    header = rows[0]
    assert header[:3] == ["company", "title", "location"]
    titles = {row[1] for row in rows[1:]}
    assert "Senior Python Engineer" in titles
    assert "C++ Systems Engineer" not in titles  # python filter excludes it


def test_export_csv_all_rows_when_no_filter(seeded_db):
    client, _ = seeded_db
    with client.stream("GET", "/api/v1/jobs/export.csv") as r:
        body = b"".join(r.iter_bytes()).decode("utf-8")
    rows = list(csv.reader(io.StringIO(body)))
    assert len(rows) == 1 + DEFAULT_TOTAL  # header + data
