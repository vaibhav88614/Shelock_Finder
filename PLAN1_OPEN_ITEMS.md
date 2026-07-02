# Plan1 — Open Items from Review

> Snapshot of items flagged in the earlier review of [Plan1.md](Plan1.md) that
> are **not yet addressed** in the implementation (as of 2026-07-01, after Task A
> + Task B landed via [backend/adapters/base.py](backend/adapters/base.py),
> [scripts/heal_seeds.py](scripts/heal_seeds.py), and
> [tests/test_retry.py](tests/test_retry.py)).
>
> **Withdrawn from the earlier review** — the POST-retry test recommendation
> (Workable/Workday POSTs are search endpoints and the retry wrapper is
> method-agnostic; the 6 existing GET tests fully cover the retry semantics).

---

## Task A — Retry / backoff

| # | Concern | Real severity | Fix sketch |
|---|---|---|---|
| A.1 | **Retry budget vs `PER_COMPANY_TIMEOUT_S = 60s`** in [backend/scrape.py](backend/scrape.py). Worst case: 3 retries × 20 s `RETRY_AFTER_CAP_S` = 60 s of pure sleep, plus the actual request time. `asyncio.wait_for` in `_scrape_one` can kill the coroutine mid-retry, silently under-counting jobs on aggressive-throttle sites. | **High** | Drop `RETRY_AFTER_CAP_S` to ~10 s **or** `MAX_RETRIES` to 2. Document the invariant "worst-case cumulative wait < `PER_COMPANY_TIMEOUT_S`" as a comment on the constants. |
| A.2 | **Retries bypass `RateLimiterGroup`.** The bucket token is acquired once in `_scrape_one` *before* `adapter.fetch()`. Retries fire additional HTTP calls that do NOT re-acquire — for a server that's already 429'ing (Personio, the main beneficiary), retries can compound the throttle rather than back off politely. | **Medium** | Pass `ats_type` (or a bound `RateLimiterGroup.acquire` callable) into `self.request(...)`; re-acquire the bucket before each retry attempt. |
| A.3 | **POST-idempotency assumption is undocumented.** The wrapper retries POST identically to GET, which is only safe because Workable/Workday POSTs are search endpoints. A future adapter that adds a mutating POST would silently double-fire on retry. | **Low** | Add a comment to `BaseAdapter.request`'s docstring stating the invariant, or introduce an opt-out (`retry_methods` class attr / `retry=False` kwarg). |
| A.5 | **`self.request` name collides visually with `httpx.AsyncClient.request`.** `self.client.request(...)` inside the wrapper reads like recursion at first glance. | **Low** (cosmetic) | Rename to `_request_with_retry` or `fetch_with_retry`; sweep the 9 adapters. |

---

## Task B — Seed auto-heal

| # | Concern | Real severity | Fix sketch |
|---|---|---|---|
| B.1 | **No name-vs-content sanity check.** "First candidate returning ≥1 job wins" — but `boards.greenhouse.io/apple`, `apple-inc`, etc. often return SOMEONE'S jobs, just not the right company's. `_verify_fix()` catches transient false-positives but does NOT catch wrong-company matches on a slug collision. | **High** | Match seed `name` tokens against the first N job titles or against the ATS's own `company_name` / board title field (Greenhouse, Lever, Ashby, Recruitee, SmartRecruiters all expose it). Reject candidates with zero token overlap. |
| B.3 | **Non-atomic write of `seeds/companies.json`.** `SEEDS.write_text(...)` directly. A Ctrl-C mid-write can corrupt the source-of-truth seed file for the whole project. | **Medium** | Write to `SEEDS.with_suffix(".json.tmp")` then `os.replace(...)`. |
| B.4 | **No audit-trail CSV.** Only stdout output. The existing `check-seeds` writes `data/seed_check.csv`; heal should follow the same pattern. | **Medium** | Emit `data/heal_report.csv` with columns `name, status, old_ats, old_id, new_ats, new_id, jobs_now, probed_at`. |
| B.5 | **Not wired into `python run.py` Typer CLI.** Stays a bare script under `scripts/`, so contributors won't discover it via `python run.py --help`. | **Medium** | Add `@app.command("heal-seeds")` in [run.py](run.py) that calls `scripts.heal_seeds.main(...)`. Consistent with `check-seeds`. |
| B.7 | **Workday partial-heal not attempted.** Currently `unfixable` short-circuits all Workday seeds. But the common pattern `<company>.wd*.myworkdayjobs.com\|<company>\|<Company>ExternalCareerSite` covers ~70% of Workday tenants in the wild. Even partial coverage is worth several companies of the 117 broken. | **Medium** | Add a Workday-specific candidate generator that tries `wd1..wd5` × `Company` casing; probe those before declaring `unfixable`. |
| B.11 | **No tests for `heal_seeds.py`.** No regression safety net for the healing logic (candidate generation, `_verify_fix`, seed rewrite). | **Medium** | Add `tests/test_heal_seeds.py` with respx-mocked probes: (a) already-ok stays unchanged, (b) broken current + working alternative → fix applied, (c) `_verify_fix` drops the change when the old config was only transiently down. |
| B.8 | **No hint for "moved to custom" cases.** Companies that migrated OFF an ATS entirely can't be auto-healed (custom needs selectors). They stay in the "STILL BROKEN" list with no guidance. | **Low** | Suffix "still broken" lines with `→ try: python run.py add-company <careers_url>` when the seed's `careers_url` responds to a HEAD request. |
| B.9 | **No pass/fail success threshold.** Report prints counts but no target. | **Low** | Set an explicit goal (e.g., "target ≥ 180/219 after Task A + B") and exit non-zero if unmet in CI mode. |

---

## Priority order (risk × effort)

1. **A.2** — rate-limit re-acquire on retry. Small change, addresses the largest correctness issue for Personio.
2. **B.1** — name-vs-content sanity check. Prevents silent seed-file corruption from wrong-company matches.
3. **B.3** — atomic write. Three lines; eliminates a real corruption class.
4. **A.1** — retry budget math. One constant change plus a comment.
5. **B.4 + B.5** — bundle: expose `python run.py heal-seeds [--dry-run]`, emit `data/heal_report.csv`. ~30 lines.
6. **B.11** — respx-mocked smoke test for the fix + verification flow.
7. Everything else — polish (A.3, A.5, B.7, B.8, B.9).

---

## Already addressed / withdrawn

For completeness, these earlier concerns are **now resolved** in the implementation
and should not be re-raised:

- `--dry-run` flag on `heal_seeds.py` — present via `argparse`.
- Retry logging — `logger.debug` calls are in `BaseAdapter.request()`.
- Retry-After HTTP-date form — documented as "falls back to computed backoff" in `_parse_retry_after`.
- `custom` / `playwright` adapters left alone — correct scope.
- Rollback plan — accurately described in Plan1.md.
- POST retry test — **withdrawn** (retry wrapper is method-agnostic; existing GET tests cover semantics; Workable/Workday POSTs are read-only).
- Concurrency + timeout numbers — set (`CONCURRENCY = 6`, `PROBE_TIMEOUT_S = 12.0`).

## Bonus wins in the implementation not called out by Plan1.md

- `_verify_fix()` sequential re-confirmation pass — catches concurrency false-positives (transient 429 on current config making an alt look better than it is).
- Rewriting `careers_url` to canonical form on fix — keeps `detect_ats()` consistent afterwards.
- 6th retry test (`test_transport_error_is_retried`) beyond the 5 the plan called for.
