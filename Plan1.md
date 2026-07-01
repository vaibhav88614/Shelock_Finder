# Plan1 — Retry/Backoff + Seed Auto-Heal

Goal: increase how many of the 219 seeded companies actually return live jobs,
by (A) making adapter HTTP requests resilient to transient throttling/errors,
and (B) auto-healing stale seed identifiers by live-probing alternative ATS
families. Both changes must be verified working before reporting back.

Baseline (measured live 2026-07-01): 82/219 companies return jobs, 10,136 jobs;
20 reachable-but-empty; 117 fail (mostly 404 stale slugs + Personio 429 +
Workday 422/410).

---

## Task A — Retry/backoff on transient failures (429/5xx/timeouts)

### Problem
Every adapter calls `self.client.get(...)` / `self.client.post(...)` exactly
once and raises `AdapterError` on any `status >= 400` or transport error. So a
single `429 Too Many Requests` (seen on all 6 Personio boards) or a transient
`503`/timeout permanently drops that company from the run.

### Change
Add one shared, centralized retry wrapper on `BaseAdapter`
([backend/adapters/base.py](backend/adapters/base.py)) and route every adapter's
HTTP call through it.

- New class attributes on `BaseAdapter`:
  - `RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})`
  - `MAX_RETRIES = 3`
  - `BACKOFF_BASE_S = 0.5`
  - `BACKOFF_CAP_S = 8.0`
  - `RETRY_AFTER_CAP_S = 20.0` (ignore absurd Retry-After so we don't exceed the
    orchestrator's 60s per-company timeout)
- New method `async def request(self, method: str, url: str, **kwargs) -> httpx.Response`:
  1. Attempt `self.client.request(method, url, **kwargs)`.
  2. On `httpx.TimeoutException` / `httpx.TransportError`: if attempts remain,
     sleep `_backoff(attempt)` and retry; else re-raise (adapters' existing
     `except httpx.HTTPError` converts it to `AdapterError`).
  3. On a response whose status is in `RETRY_STATUSES`: if attempts remain,
     sleep `min(Retry-After, RETRY_AFTER_CAP_S)` when the header is present and
     parseable, else `_backoff(attempt)`; then retry. Else return the response
     (caller raises `AdapterError` with the status as today).
  4. Otherwise return the response immediately (200, 404, etc. — 404 is terminal
     and must NOT be retried).
- `_backoff(attempt)` = `min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2**attempt)` plus
  random jitter in `[0, BACKOFF_BASE_S)` (full-jitter style) to avoid thundering
  herd. `import asyncio, random` at top of base.py.
- `_parse_retry_after(resp)` handles integer-seconds form (the common case);
  returns `None` for HTTP-date or unparseable values (falls back to backoff).

### Adapters to update (swap `self.client.<verb>` → `self.request(...)`)
All keep their surrounding `try/except httpx.HTTPError` and status checks:
- [greenhouse.py](backend/adapters/greenhouse.py): `get` → `request("GET", url)`
- [lever.py](backend/adapters/lever.py): `get`
- [ashby.py](backend/adapters/ashby.py): `get`
- [smartrecruiters.py](backend/adapters/smartrecruiters.py): `get`
- [recruitee.py](backend/adapters/recruitee.py): `get`
- [teamtailor.py](backend/adapters/teamtailor.py): `get`
- [personio.py](backend/adapters/personio.py): `get` (with `headers=`) — the main
  429 beneficiary
- [workable.py](backend/adapters/workable.py): `post` (with `json=`)
- [workday.py](backend/adapters/workday.py): `post` (with `json=` and `headers=`)

`custom` and `playwright` adapters are left as-is (HTML/browser paths, not the
source of the throttling seen).

### Interaction with existing rate limiter
`RateLimiterGroup` already gates *outbound* rate per ATS. Retry/backoff handles
the *server pushing back anyway*. They're complementary; no change to
[rate_limit.py](backend/rate_limit.py).

### Tests (new `tests/test_retry.py`, respx-mocked, `asyncio.sleep` monkeypatched to no-op)
1. `429` twice then `200` → adapter returns jobs; exactly 3 HTTP calls made.
2. `503` then `200` → success on 2nd call.
3. `404` → raises `AdapterError` immediately; exactly 1 call (no retry).
4. `429` on every attempt → after `MAX_RETRIES+1` calls, raises `AdapterError`.
5. `Retry-After: 1` respected (assert sleep called with ~1s via a capture).

---

## Task B — Auto-heal stale seed identifiers (live-verified)

### Problem
117 seeds fail, almost all because the company moved ATS or renamed its board
(e.g. Notion/Shopify/Slack no longer on the seeded Greenhouse slug; Netflix off
Lever; all 8 Teamtailor slugs 404). These need corrected `ats_type` /
`ats_identifier`, not code changes.

### Change
Add a maintenance tool `scripts/heal_seeds.py` (kept — genuinely useful, sibling
to the existing `check-seeds`). It:
1. Loads `seeds/companies.json`.
2. Live-probes each company with its **current** `(ats_type, ats_identifier)`
   using the real adapters. If it returns >=1 job → leave unchanged.
3. For each failing company, generates candidates and probes them **live**:
   - identifier candidates (deduped): current identifier, and a slug of the
     company name (lowercased, non-alphanumeric stripped; also a hyphenated
     variant).
   - family candidates: `ashby, greenhouse, lever, workable, smartrecruiters,
     recruitee, teamtailor` (skip `workday` — needs a 3-part host|tenant|site id
     that can't be guessed; skip `personio` in candidate-probing to avoid its
     aggressive 429s, though existing personio seeds still get retry benefit).
   - The first candidate that returns >=1 live job is accepted as the fix.
4. Writes corrected entries back to `seeds/companies.json` (preserving key order
   and the file's overall shape), and prints a full before/after report:
   fixed (old → new), still-broken, and unchanged.
5. Safety: only applies a change that was **confirmed live**; identifiers are
   derived from the company itself (current id or its name slug) to minimize the
   small risk of slug collisions. The change is reviewable via `git diff`.

Concurrency-bounded (semaphore) with a short per-probe timeout so the whole run
finishes in a few minutes; uses the shared client + the new retry wrapper.

### Verification
- Re-run the same full live probe used for the baseline and show the new
  `returns-jobs` count and total jobs (expect a meaningful jump — at minimum the
  6 Personio boards recovered by Task A, plus every board Task B re-points).
- Optionally spot-check 3–4 healed companies by name in the output.

---

## Execution order
1. Implement Task A (base.py + 9 adapters).
2. Add `tests/test_retry.py`; run full `pytest` → expect all green.
3. Implement `scripts/heal_seeds.py`.
4. Run it live; it rewrites `seeds/companies.json` with confirmed fixes.
5. Re-run the full live probe; capture before/after numbers.
6. Run `pytest` once more (seed-count tests in `tests/test_seeds.py` must still
   pass after the JSON changes) and `npm run build` (unaffected, sanity only).
7. Report: what changed, test results, and the new live coverage numbers.

## Rollback
- Task A is additive; reverting base.py + adapter one-liners restores prior
  behavior.
- Task B only edits `seeds/companies.json`; `git checkout seeds/companies.json`
  restores the original seeds.

---

## Results (executed 2026-07-01)

- Task A: implemented `BaseAdapter.request()` retry wrapper + routed all 9 ATS
  adapters through it. New `tests/test_retry.py` (6 tests) all pass. Full suite:
  **157 passed** (was 151).
- Task B: `scripts/heal_seeds.py` discovered candidates concurrently, then
  verified each sequentially (OLD must fail + NEW must return jobs). **57 fixes
  applied** (1 dry-run candidate — Hugging Face — correctly dropped by the
  verification guard). Seed validation tests still pass.
- Live coverage before → after: **82 → 135** companies returning jobs (of 219);
  **10,136 → 13,878** live jobs. Examples re-pointed: Notion, Cohere, Plaid,
  Ramp, Sentry, Linear, PostHog, Replit, Supabase, Zapier → Ashby; Klaviyo,
  Toast, Postman, Tide → Greenhouse; Spotify, Shield AI → Lever.
- Remaining ~72 still-broken are mostly Workday tenant errors (need 3-part
  host|tenant|site, unguessable) and companies on ATSes/pages not covered by a
  guessable identifier (e.g. Slack, Shopify, DoorDash, Netflix).
