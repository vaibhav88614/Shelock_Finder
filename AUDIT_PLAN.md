# JobPulse Audit — Comprehensive Plan

> Audit conducted 2026-07-01. Two-stage approach: a Plan-mode audit found
> frontend / a11y / perf / FTS5 issues; an independent Cursor audit (which
> ran pytest) found a failing test plus backend retention/isolation/deprecation
> issues. Findings were merged into the six-phase plan below.

**Attribution legend**
- `[P]` — caught by Plan-mode audit
- `[C]` — caught by Cursor audit
- `[P+C]` — both independently identified

---

## TL;DR

A multi-area audit of JobPulse (Python/FastAPI backend, React/Vite/Tailwind
frontend, SQLite+FTS5, 11 ATS adapters, pytest suite) found:

| Severity | Count | Examples |
|---|---|---|
| Test-suite-breaking bug | 1 | Retention prune deletes inactive jobs same-run |
| Real bugs | 5 | Per-company isolation gaps, status-display mismatch, frontend missing X-API-Key, delta CSV buffers all rows, bulk modal doesn't close |
| Correctness / robustness | 9 | utcnow deprecation, README API drift, FTS5 idempotency, silent dropped jobs, adapter leak, etc. |
| Accessibility gaps | 4 | No Escape close, no focus trap, no ErrorBoundary, missing aria-live |
| Performance / ops | 7 | No composite indexes, WAL never truncates, cursor NULL-tail scan, raw_payload stored unused, no chunked persist |
| Test-coverage gaps | 7 | No rate_limit tests, no POST /scrape-runs tests, no auth gate tests, no migration tests, etc. |

**Baseline**: 116 / 117 pytest before any edits. Goal: zero defects, ≥ 137 tests, frontend builds clean with stricter TypeScript.

---

## Resolved design decisions (user-aligned)

1. **`posted_within_days` cap** — keep default of 15, expose `JOBPULSE_POSTED_WITHIN_DAYS_MAX` env knob.
2. **`raw_payload`** — opt-in via `JOBPULSE_STORE_RAW_PAYLOAD=1` (default off); separate `vacuum-payloads` CLI for backfill (not implemented in this audit; flagged as future work).
3. **API-key transport** — settings UI in Admin page writes to `localStorage`, with `VITE_API_KEY` build-time fallback.
4. **Focus trap** — use `react-focus-lock` (~5 KB gz) rather than hand-rolled.
5. **`@lru_cache` on `get_settings()`** — **declined**; module-level singleton already serves this and the decorator would be a foot-gun for test fixtures.
6. **`tenacity`** — **drop** (currently unused in the codebase) rather than wire it into adapter retries.
7. **Cursor pagination encoding** — non-breaking change preserved (no new prefix needed; the empty-sv sentinel already encodes the "null-tail" phase).

---

## Phase 1 — Critical bugs (6 items, blocks V1 baseline green)

| ID | Source | What | Files |
|---|---|---|---|
| 1.1 | `[C]` | **Retention prune deletes inactive jobs same-run.** `_finalize_run` deleted `is_active=False AND (posted_date IS NULL OR posted_date < cutoff)` — wipes any inactive job with no posted_date instantly, and wipes posted_date-aged jobs the very run they go inactive. Fix: key retention on `last_seen_at` instead. **Root cause of the failing test.** | `backend/scrape.py` |
| 1.2 | `[C]` | **Per-company isolation gaps.** `_scrape_one` wrapped only `adapter.fetch()`; `_load_company_snapshot` and `_persist_company` were unwrapped. `gather(*tasks, return_exceptions=False)` propagated any escape and aborted the run (contradicting spec §6). Fix: wrap both paths; use `gather(return_exceptions=True)` with a backstop conversion. | `backend/scrape.py` |
| 1.3 | `[P]` | **Status display always red.** Backend writes `"ok"` / `"partial"` / `"failed"`; frontend `AdminPage.tsx` checked `r.status === "success"` — never matches. Map "ok"→emerald, "partial"→amber, "running"→slate, "failed"→red. Add `ScrapeRunStatus` literal union. | `frontend/src/components/AdminPage.tsx`, `frontend/src/types.ts` |
| 1.4 | `[P+C]` | **Frontend never sends `X-API-Key`.** Setting `JOBPULSE_API_KEY` silently 401s every UI mutation. Add `getApiKey/setApiKey/clearApiKey`, `mutateHeaders`, settings panel on Admin page, `VITE_API_KEY` build-time fallback. | `frontend/src/api.ts`, `frontend/src/components/AdminPage.tsx`, NEW `frontend/src/vite-env.d.ts` |
| 1.5 | `[P]` | **Delta CSV buffers all rows.** `_write_delta_csv` used `.all()`; switch to `.execution_options(yield_per=500)` matching the API export. | `backend/scrape.py` |
| 1.6 | `[P]` | **Bulk-import modal doesn't close on success.** Add aria-live region, change "Close" → "Done — close" once result is shown, auto-focus the close button on success. | `frontend/src/components/AddCompanyModal.tsx` |

---

## Phase 2 — Correctness, robustness, deprecations (10 items)

| ID | Source | What | Files |
|---|---|---|---|
| 2.1 | `[C]` | **`datetime.utcnow()` deprecated in Python 3.13.** 10 call sites + 1 in `tests/conftest.py`. Define `utcnow_naive()` in `backend/models.py`, alias `_utcnow` to it, replace every site. Loosen `pytest.ini` from `ignore::DeprecationWarning` → `default::DeprecationWarning`. | `backend/models.py`, `backend/scrape.py`, `backend/api/{filters,jobs,stats}.py`, `backend/adapters/workday.py`, `tests/conftest.py`, `pytest.ini` |
| 2.2 | `[C]` | **README ↔ API contract drift.** GET `/jobs` listed non-existent params (`q`, `since`, `keyword_any`, `keyword_all`, `company_id`, `remote`); `POST /companies/bulk` was the wrong path. Rewrite the API table from actual route definitions; document FTS5/LIKE keyword behavior. | `README.md` |
| 2.3 | `[C]` | **`posted_within_days` hard-capped at 15 in two places.** Centralize as `POSTED_WITHIN_DAYS_MAX` constant in `filters.py`, parameterize via `JOBPULSE_POSTED_WITHIN_DAYS_MAX` env knob. | `backend/config.py`, `backend/api/filters.py`, `backend/api/jobs.py` |
| 2.4 | `[P]` | **FTS5 migration not idempotent.** Guard `CREATE VIRTUAL TABLE jobs_fts` with `sqlite_master` lookup; use `CREATE TRIGGER IF NOT EXISTS`. | `backend/alembic/versions/0002_fts5_jobs.py` |
| 2.5 | `[P]` | **Silent dropped jobs.** `_persist_company` silently `continue`d on empty `title`/`apply_url`; log a warning. | `backend/scrape.py` |
| 2.6 | `[P]` | **Per-adapter httpx clients leak.** Orchestrator never called `adapter.aclose()`. Wrap `gather()` in try/finally, await aclose on every cached adapter. | `backend/scrape.py` |
| 2.7 | `[P]` | **Workable 5000-job cap silent.** Promote the truncation message from `logger.debug` to `logger.warning`, fire only when the cap actually triggers. | `backend/adapters/workable.py` |
| 2.8 | `[P]` | **Stale closure in `Filters.tsx` debounce.** Replace eslint-disable + closure-stale comparison with `useRef`s for `value`/`onChange`. | `frontend/src/components/Filters.tsx` |
| 2.9 | `[P]` | **AdminPage `refetchInterval` inline.** Hoist callback to module scope so identity is stable across renders. | `frontend/src/components/AdminPage.tsx` |
| 2.10 | `[P]` | **Background scrape `_job` swallows exceptions.** Replace `except Exception: pass` with `logger.exception(...)`. | `backend/api/scrape_runs.py` |

---

## Phase 3 — Accessibility & UX (4 items)

| ID | Source | What | Files |
|---|---|---|---|
| 3.1 | `[P]` | **Escape-to-close** on both modals via a shared `useEscapeToClose(onClose)` hook. | NEW `frontend/src/hooks/useEscapeToClose.ts`, `JobDrawer.tsx`, `AddCompanyModal.tsx` |
| 3.2 | `[P]` | **Focus trap** via `react-focus-lock@^2.13.0` (`<FocusLock returnFocus>` wraps both modals). | `frontend/package.json`, `JobDrawer.tsx`, `AddCompanyModal.tsx` |
| 3.3 | `[P]` | **Root-level ErrorBoundary** with reload-page fallback. Wraps `<App/>`. | NEW `frontend/src/components/ErrorBoundary.tsx`, `frontend/src/main.tsx` |
| 3.4 | `[P]` | **A11y/polish bundle**: `aria-live`+`aria-busy` on JobTable; `aria-label` on AdminPage sort `<select>`; `<meta name="description">`, `<meta name="theme-color">`, inline-SVG favicon in `index.html`; `/health` link gated behind `import.meta.env.DEV`. | `frontend/src/components/JobTable.tsx`, `frontend/src/components/AdminPage.tsx`, `frontend/index.html`, `frontend/src/App.tsx` |

---

## Phase 4 — Performance & ops (7 items)

| ID | Source | What | Files |
|---|---|---|---|
| 4.1 | `[P+C]` | **Composite indexes** — new Alembic migration with `ix_jobs_posted_date_id_desc`, `ix_jobs_first_seen_id_desc` ([P] for cursor keysets), and `ix_jobs_company_last_seen` ([C] for `_finalize_run` UPDATE + DELETE). | NEW `backend/alembic/versions/0003_cursor_and_finalize_indexes.py` |
| 4.2 | `[P]` | **Cursor NULL-tail optimization.** Drop the `sort_col.is_(None)` disjunct from the non-null keyset clause; emit a null-tail cursor at the transition. Cursor format stays backwards-compatible — the existing empty-sv signals null-tail phase. | `backend/api/filters.py`, `backend/api/jobs.py` |
| 4.3 | `[C]` | **WAL never truncates.** Add `PRAGMA wal_autocheckpoint=1000` at connect; run `PRAGMA wal_checkpoint(TRUNCATE)` + `PRAGMA optimize` at end of `_finalize_run`. | `backend/db.py`, `backend/scrape.py` |
| 4.4 | `[C]` | **`raw_payload` always stored, never read.** Gate on `JOBPULSE_STORE_RAW_PAYLOAD` env var (default off). | `backend/config.py`, `backend/scrape.py` |
| 4.5 | `[C]` | **`_persist_company` chunked persist.** Process upserts in 500-row batches with `s.flush()` between chunks — bounds memory + writer-lock hold for large boards. | `backend/scrape.py` |
| 4.6 | `[P]` | **Stable RQ keys** — `queryKey: ["jobs", filters]` → individual fields so future filter-object recreations don't bust the cache. | `frontend/src/App.tsx` |
| 4.7 | `[P]` | **`React.memo` + `useCallback`** on JobTable, Filters, StatsBar; memoize `handleExport`/`handleLoadMore`/`handleAddClose`/`handleDrawerClose`. | `frontend/src/components/*.tsx`, `frontend/src/App.tsx` |

---

## Phase 5 — Test coverage (7 items, all done)

| ID | Source | What | New / changed file |
|---|---|---|---|
| 5.1 | `[P]` | **Rate-limit tests.** 5 tests: initial burst, default fallback, drain+refill timing, key isolation, concurrent serialization. | NEW `tests/test_rate_limit.py` |
| 5.2 | `[P]` | **POST `/scrape-runs` tests.** 4 tests: 202 queued, query-param passthrough, 409 when in-flight, allows-new-after-finished. | NEW `tests/test_api_scrape_runs_post.py` |
| 5.3 | `[P]` | **X-API-Key gate tests.** 7 tests covering POST `/companies` + POST `/scrape-runs` under no-key/missing-header/wrong-header/correct-header, plus GET-endpoints-stay-open. | NEW `tests/test_api_auth.py` |
| 5.4 | `[P]` | **CustomAdapter extended tests.** 10 tests: missing/blank required keys, non-JSON selectors, missing custom_selectors attribute, relative URL absolutization (root-relative + scheme-relative), detail-page enrichment (with 404 graceful degradation), `list_url` overrides `careers_url`. | NEW `tests/test_custom_adapter_extended.py` |
| 5.5 | `[P]` | **Migration tests.** 5 tests: idempotency (Phase 2.4), FTS5 table+triggers present, insert-trigger sync, delete-trigger sync, downgrade + re-upgrade. | NEW `tests/test_migrations.py` |
| 5.6 | `[P]` | **Workable pagination tests.** 3 tests: token-chain pagination across 3 pages, 5000-cap warning fires once, under-cap emits no warning. | NEW `tests/test_workable_pagination.py` |
| 5.7 | `[C]` | **Stabilize `test_scrape_full_dedupe_lifecycle`.** Add `lever_payload_now` fixture rewriting `createdAt` to "now − N days"; add `stepping_clock` fixture monkey-patching `backend.scrape.utcnow_naive`; remove both `time.sleep(1.1)` calls. ~2.2s of test time saved + no more time-rot. | `tests/conftest.py`, `tests/test_scrape_orchestrator.py` |

Also added `captured_logs` fixture in `tests/conftest.py` for loguru-based assertions (used by 5.6).

---

## Phase 6 — Polish / cleanup (9 items; 6 done, 1 declined, 2 in)

| ID | Source | Status | What | Files |
|---|---|---|---|---|
| 6.1 | `[P]` | ✅ done | `"noUncheckedIndexedAccess": true`. Surfaced 1 site (`deriveName` in AddCompanyModal); fixed with `?? host` fallback. | `frontend/tsconfig.json`, `frontend/src/components/AddCompanyModal.tsx` |
| 6.2 | `[P]` | ✅ done | `VITE_API_BASE` env var. `.env.example` documenting both `VITE_API_BASE` and `VITE_API_KEY`. | `frontend/src/api.ts`, NEW `frontend/.env.example` |
| 6.3 | `[P+C]` | ✅ done | README rewrite — bundled into Phase 2.2. | `README.md` |
| 6.4 | `[P]` | ✅ done | `JOBPULSE_DEV_ORIGINS` env knob (comma-separated) spread into CORS `allow_origins`. | `backend/config.py`, `backend/serve.py` |
| 6.5 | `[P]` | ✅ done | CSV export via `downloadJobsCsv` (fetch + Blob + download link); `useMutation` wraps it; error banner on failure. | `frontend/src/api.ts`, `frontend/src/App.tsx` |
| 6.6 | `[C]` | ✅ done | Dropped `tenacity==9.0.0` (zero imports). Lock file note: regenerate `requirements.lock` with `uv pip compile`. | `backend/requirements.txt` |
| 6.7 | `[C]` | ❌ declined | `@lru_cache` on `get_settings()` — module-level singleton already serves this. | (no change) |
| 6.8 | `[C]` | ✅ done | Bundle splitting via `rollupOptions.output.manualChunks`. Splits into 4 chunks: react / query / focuslock / app code. | `frontend/vite.config.ts` |
| 6.9 | `[C]` | ✅ done | GitHub Actions CI workflow with backend (pytest) + frontend (`npm run build`) jobs. | NEW `.github/workflows/ci.yml` |

---

## Verification gates

- **V1** — Baseline pytest before any edits: 116 passed, 1 failed (`test_scrape_full_dedupe_lifecycle`). Matches Cursor's empirical run.
- **V2** — After Phase 1: pytest 117/117 (1.1 fixed the failing test by design).
- **V3** — After Phase 2: pytest 117/117 + zero DeprecationWarnings under `-W default::DeprecationWarning`.
- **V4** — After Phase 3: frontend builds clean (218 → 239 KB; +21 KB for react-focus-lock).
- **V5** — After Phase 4: pytest 117/117; SQLite migrations show 3 new composite indexes; WAL checkpoint runs at end of every scrape.
- **V6** — After Phase 5: pytest **151 passed** (+34 new tests across 6 new files); Phase 5.7 cuts ~2.2 s from `test_scrape_full_dedupe_lifecycle`.
- **V7** — After Phase 6: frontend `tsc -b` passes with `noUncheckedIndexedAccess`; build emits 4-way split bundle (react 133.93 KB / query 50.31 KB / focuslock 19.72 KB / app 36.32 KB).

---

## Operational notes for users on the v2 build

- **New env knobs**: `JOBPULSE_POSTED_WITHIN_DAYS_MAX` (default 15), `JOBPULSE_STORE_RAW_PAYLOAD` (default off), `JOBPULSE_DEV_ORIGINS` (default empty).
- **New frontend dep**: `react-focus-lock@^2.13.0`. Run `npm install` in `frontend/` on a fresh clone.
- **New migration `0003_cursor_and_finalize_indexes`** applies automatically on `python run.py migrate` or `python run.py serve`.
- **Existing 98 MB `.db-wal`** will collapse the next time a scrape finishes (Phase 4.3 truncate).
- **`requirements.lock`** still contains `tenacity`. Regenerate when convenient with `uv pip compile backend/requirements.txt -o requirements.lock --generate-hashes`.
- **CI workflow** is opt-in: it activates the moment the repo is pushed to GitHub. Local-only users can ignore.

---

## Future-work items intentionally deferred

- **Virtualize JobTable** rows (`@tanstack/react-virtual`) — only useful past ~1000 loaded rows; the existing "Load more" caps each fetch at 50.
- **Playwright adapter tests** — need a browser install; gate behind `pytest -m playwright`.
- **`python run.py vacuum-payloads`** CLI to backfill-NULL existing `raw_payload` columns when toggling Phase 4.4 off after-the-fact.
- **Tenacity-driven adapter retries** on 429/503 — feature, not fix. Plan dropped the dep instead.
- **`raw_payload` column drop** via Alembic migration — keep the column for users who toggle the env knob on.
