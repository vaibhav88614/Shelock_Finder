import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  bulkSetCompaniesActive,
  cleanupOldJobs,
  clearApiKey,
  fetchCompanyHealth,
  fetchRuns,
  getApiKey,
  setApiKey,
  triggerScrape,
  triggerScrapeAll,
  updateCompany,
} from "../api";
import type { CleanupJobsResult, CompanyHealth, ScrapeRun } from "../types";

type SortKey = "failures" | "name" | "last_success" | "jobs_active";

// ATS families driven by CSS selectors — the "custom markers" the master
// toggle is asked to leave alone.
const CUSTOM_ATS_TYPES = new Set(["custom", "playwright"]);

// Module-scoped so the `refetchInterval` option keeps a stable identity
// across renders — React-Query treats new option identities as a fresh
// config and would otherwise thrash polling timers on every parent render.
function runsRefetchInterval(q: {
  state: { data: ScrapeRun[] | undefined };
}): number | false {
  return q.state.data?.some((r) => r.finished_at === null) ? 3000 : false;
}

function fmtAgo(iso: string | null): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "—";
  const mins = Math.floor(ms / 60_000);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toISOString().replace("T", " ").slice(0, 19) + "Z";
}

function sortHealth(rows: CompanyHealth[], key: SortKey): CompanyHealth[] {
  const copy = [...rows];
  switch (key) {
    case "name":
      return copy.sort((a, b) => a.name.localeCompare(b.name));
    case "jobs_active":
      return copy.sort((a, b) => b.jobs_active - a.jobs_active);
    case "last_success":
      return copy.sort((a, b) => {
        const av = a.last_success_at ? new Date(a.last_success_at).getTime() : 0;
        const bv = b.last_success_at ? new Date(b.last_success_at).getTime() : 0;
        return bv - av;
      });
    case "failures":
    default:
      return copy.sort(
        (a, b) =>
          b.consecutive_failures - a.consecutive_failures ||
          a.name.localeCompare(b.name)
      );
  }
}

// Rows targeted by the master toggle: non-failing AND non-custom-marker.
// These are the "reliable, standard-ATS" companies the user can flip in bulk
// without touching the flakier custom/playwright pipeline.
function isMasterCandidate(r: CompanyHealth): boolean {
  return r.consecutive_failures === 0 && !CUSTOM_ATS_TYPES.has(r.ats_type);
}

export function AdminPage() {
  const qc = useQueryClient();
  const [sortKey, setSortKey] = useState<SortKey>("failures");
  const [filterText, setFilterText] = useState("");
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const [apiKeyMessage, setApiKeyMessage] = useState<string | null>(null);
  const [apiKeyConfigured, setApiKeyConfigured] = useState<boolean>(
    () => getApiKey() !== null
  );
  const [healthOpen, setHealthOpen] = useState(true);
  const [cleanupDays, setCleanupDays] = useState(30);
  const [cleanupResult, setCleanupResult] = useState<CleanupJobsResult | null>(null);

  const health = useQuery({ queryKey: ["company-health"], queryFn: fetchCompanyHealth });
  const runs = useQuery({
    queryKey: ["runs", "admin"],
    queryFn: () => fetchRuns(25),
    // Poll while a run is in-flight so the UI catches the finished_at update.
    refetchInterval: runsRefetchInterval,
  });

  const inFlight = (runs.data ?? []).find((r) => r.finished_at === null) ?? null;

  const scrape = useMutation({
    mutationFn: (id: number) => triggerScrape(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["company-health"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const scrapeAll = useMutation({
    mutationFn: (opts: { noPlaywright: boolean }) =>
      triggerScrapeAll({ noPlaywright: opts.noPlaywright }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["company-health"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const toggleScrape = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      updateCompany(id, { active }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["company-health"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const bulkToggle = useMutation({
    mutationFn: ({ ids, active }: { ids: number[]; active: boolean }) =>
      bulkSetCompaniesActive({ ids, active }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["company-health"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const cleanup = useMutation({
    mutationFn: (opts: { days: number; dryRun: boolean }) =>
      cleanupOldJobs(opts.days, opts.dryRun),
    onSuccess: (data, vars) => {
      setCleanupResult(data);
      if (!vars.dryRun) {
        qc.invalidateQueries({ queryKey: ["stats"] });
        qc.invalidateQueries({ queryKey: ["jobs"] });
      }
    },
  });

  const onScrapeAll = (noPlaywright: boolean) => {
    const label = noPlaywright ? "all companies (skipping Playwright sites)" : "all active companies";
    if (!window.confirm(`Start a full scrape of ${label}? This takes 1–5 minutes.`)) return;
    scrapeAll.mutate({ noPlaywright });
  };

  const onSaveApiKey = () => {
    const v = apiKeyDraft.trim();
    if (v) {
      setApiKey(v);
      setApiKeyConfigured(true);
      setApiKeyMessage("API key saved to this browser.");
    } else {
      clearApiKey();
      setApiKeyConfigured(false);
      setApiKeyMessage("API key cleared.");
    }
    setApiKeyDraft("");
  };

  const onClearApiKey = () => {
    clearApiKey();
    setApiKeyDraft("");
    setApiKeyConfigured(false);
    setApiKeyMessage("API key cleared.");
  };

  const rows = useMemo(
    () =>
      sortHealth(health.data ?? [], sortKey).filter((r) =>
        !filterText ? true : r.name.toLowerCase().includes(filterText.toLowerCase())
      ),
    [health.data, sortKey, filterText]
  );

  const failing = (health.data ?? []).filter((r) => r.consecutive_failures > 0).length;
  const inactive = (health.data ?? []).filter((r) => !r.active).length;
  const customRows = (health.data ?? []).filter((r) => r.has_selectors);
  const customScrapeOn = customRows.filter((r) => r.active).length;

  // Master-toggle candidates: non-failing, non-custom-marker.
  const masterCandidates = useMemo(
    () => (health.data ?? []).filter(isMasterCandidate),
    [health.data]
  );
  const masterOn = masterCandidates.filter((r) => r.active).length;
  const masterOff = masterCandidates.length - masterOn;
  // Default the master toggle to "turn everything ON when more than half is
  // currently off". A single click either enables the whole batch or disables
  // it — an explicit confirm gate covers the destructive direction.
  const masterNextActive = masterOn <= masterOff;

  const runMasterToggle = () => {
    const ids = masterCandidates.map((r) => r.id);
    if (ids.length === 0) return;
    const verb = masterNextActive ? "Enable" : "Disable";
    if (
      !window.confirm(
        `${verb} scraping for ${ids.length} standard-ATS companies (no custom selectors, no failures)?`
      )
    ) {
      return;
    }
    bulkToggle.mutate({ ids, active: masterNextActive });
  };

  const runCleanup = (dryRun: boolean) => {
    if (!dryRun) {
      if (
        !window.confirm(
          `Delete jobs not seen for ${cleanupDays}+ days? This can't be undone.`
        )
      ) {
        return;
      }
    }
    cleanup.mutate({ days: cleanupDays, dryRun });
  };

  const sectionCls =
    "bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg p-4 shadow-sm";

  return (
    <div className="space-y-5">
      <section
        className={`${sectionCls} flex flex-wrap items-center justify-between gap-3`}
      >
        <div>
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">Scrape control</h2>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {inFlight
              ? `Run #${inFlight.id} in progress — started ${fmtAgo(inFlight.started_at)} ago.`
              : "No scrape is currently running."}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            disabled={!!inFlight || scrapeAll.isPending}
            onClick={() => onScrapeAll(false)}
            className="text-sm bg-slate-900 text-white rounded px-3 py-1.5 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
            title="Scrape every active company"
          >
            {inFlight ? "Scraping…" : scrapeAll.isPending ? "Queueing…" : "Scrape all"}
          </button>
          <button
            type="button"
            disabled={!!inFlight || scrapeAll.isPending}
            onClick={() => onScrapeAll(true)}
            className="text-xs border border-slate-300 dark:border-slate-700 rounded px-3 py-1.5 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"
            title="Skip Playwright-tier sites (faster)"
          >
            Scrape all (no Playwright)
          </button>
        </div>
        {scrapeAll.isError && (
          <div className="basis-full text-xs text-red-700 dark:text-red-400">
            {(scrapeAll.error as Error).message}
          </div>
        )}

        {/* Master toggle — only targets non-failing, non-custom-marker rows */}
        <div className="basis-full border-t border-slate-200 dark:border-slate-800 pt-3 mt-1 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-xs font-semibold text-slate-700 dark:text-slate-200">
              Master scrape toggle
            </h3>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 max-w-2xl">
              Bulk-flip the <strong>{masterCandidates.length}</strong> standard-ATS
              companies with zero consecutive failures. Custom / Playwright
              companies and any company currently failing are excluded — use
              the per-row toggle below to change those individually.
            </p>
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              Currently <strong>{masterOn}</strong> on ·{" "}
              <strong>{masterOff}</strong> off in this set.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={
                masterCandidates.length === 0 ||
                bulkToggle.isPending ||
                !!inFlight
              }
              onClick={runMasterToggle}
              className={`text-sm rounded px-3 py-1.5 disabled:opacity-50 disabled:cursor-not-allowed ${
                masterNextActive
                  ? "bg-emerald-600 text-white hover:bg-emerald-500"
                  : "bg-amber-600 text-white hover:bg-amber-500"
              }`}
              title={
                masterCandidates.length === 0
                  ? "No eligible companies"
                  : masterNextActive
                  ? "Enable scraping for all eligible companies"
                  : "Disable scraping for all eligible companies"
              }
            >
              {bulkToggle.isPending
                ? "Updating…"
                : masterNextActive
                ? `Enable ${masterCandidates.length} companies`
                : `Disable ${masterCandidates.length} companies`}
            </button>
          </div>
          {bulkToggle.isSuccess && bulkToggle.data && (
            <div className="basis-full text-[11px] text-emerald-700 dark:text-emerald-400">
              Master toggle applied — {bulkToggle.data.updated} of{" "}
              {bulkToggle.data.matched} rows changed.
            </div>
          )}
          {bulkToggle.isError && (
            <div className="basis-full text-[11px] text-red-700 dark:text-red-400">
              Bulk update failed: {(bulkToggle.error as Error).message}
            </div>
          )}
        </div>

        {/* Cleanup old jobs */}
        <div className="basis-full border-t border-slate-200 dark:border-slate-800 pt-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-xs font-semibold text-slate-700 dark:text-slate-200">
              Cleanup old jobs
            </h3>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 max-w-2xl">
              Delete jobs whose <code>last_seen_at</code> is older than the
              cutoff. A job that keeps reappearing on a careers page is
              refreshed on every scrape, so this only removes truly stale rows.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-600 dark:text-slate-300 flex items-center gap-1">
              Older than
              <input
                type="number"
                min={1}
                max={365}
                value={cleanupDays}
                onChange={(e) =>
                  setCleanupDays(
                    Math.max(1, Math.min(365, Number(e.target.value) || 30))
                  )
                }
                className="w-16 border border-slate-300 dark:border-slate-700 dark:bg-slate-900 rounded px-2 py-1 text-xs"
              />
              days
            </label>
            <button
              type="button"
              disabled={cleanup.isPending}
              onClick={() => runCleanup(true)}
              className="text-xs border border-slate-300 dark:border-slate-700 rounded px-3 py-1.5 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50"
            >
              Preview
            </button>
            <button
              type="button"
              disabled={cleanup.isPending}
              onClick={() => runCleanup(false)}
              className="text-sm bg-red-600 text-white rounded px-3 py-1.5 hover:bg-red-500 disabled:opacity-50"
            >
              {cleanup.isPending ? "Working…" : "Delete"}
            </button>
          </div>
          {cleanupResult && (
            <div className="basis-full text-[11px] text-slate-600 dark:text-slate-300">
              {cleanupResult.dry_run
                ? `Preview: ${cleanupResult.matched} jobs older than the cutoff (${cleanupResult.cutoff.slice(0, 10)}).`
                : `Deleted ${cleanupResult.deleted} of ${cleanupResult.matched} matching jobs.`}
            </div>
          )}
          {cleanup.isError && (
            <div className="basis-full text-[11px] text-red-700 dark:text-red-400">
              Cleanup failed: {(cleanup.error as Error).message}
            </div>
          )}
        </div>
      </section>

      <section className={sectionCls}>
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">API key</h2>
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">
          Required only when the server is started with{" "}
          <code className="bg-slate-100 dark:bg-slate-800 px-1 rounded">JOBPULSE_API_KEY</code>{" "}
          set. Stored locally in this browser only.
          {apiKeyConfigured && (
            <span className="ml-1 text-emerald-700 dark:text-emerald-400">
              • a key is currently configured
            </span>
          )}
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-slate-600 dark:text-slate-300 flex flex-col flex-1 min-w-[240px]">
            X-API-Key
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              className="mt-1 border border-slate-300 dark:border-slate-700 dark:bg-slate-900 rounded px-2 py-1.5 text-sm font-mono"
              value={apiKeyDraft}
              onChange={(e) => setApiKeyDraft(e.target.value)}
              placeholder={
                apiKeyConfigured
                  ? "•••••• (key configured — paste a new one to replace)"
                  : "paste key here"
              }
            />
          </label>
          <button
            type="button"
            onClick={onSaveApiKey}
            className="text-sm bg-slate-900 text-white rounded px-3 py-1.5 hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900"
          >
            Save
          </button>
          <button
            type="button"
            onClick={onClearApiKey}
            disabled={!apiKeyConfigured}
            className="text-xs border border-slate-300 dark:border-slate-700 rounded px-3 py-1.5 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Clear
          </button>
        </div>
        {apiKeyMessage && (
          <div
            className="text-xs text-emerald-700 dark:text-emerald-400 mt-2"
            aria-live="polite"
          >
            {apiKeyMessage}
          </div>
        )}
      </section>

      <section className={sectionCls}>
        <button
          type="button"
          onClick={() => setHealthOpen((v) => !v)}
          aria-expanded={healthOpen}
          aria-controls="per-company-health-body"
          className="w-full flex items-center justify-between gap-2 -m-1 p-1 rounded hover:bg-slate-50 dark:hover:bg-slate-800/50"
        >
          <span className="flex items-center gap-2">
            <span
              aria-hidden
              className={`inline-block transition-transform ${healthOpen ? "rotate-90" : ""}`}
            >
              ▶
            </span>
            <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              Per-company health
            </h2>
          </span>
          <span className="text-xs text-slate-500 dark:text-slate-400">
            <strong>{(health.data ?? []).length}</strong> total ·{" "}
            <strong>{failing}</strong> failing · <strong>{inactive}</strong>{" "}
            inactive · <strong>{customScrapeOn}</strong>/{customRows.length}{" "}
            custom scrape on
          </span>
        </button>

        {healthOpen && (
          <div id="per-company-health-body" className="mt-4">
            <div className="flex flex-wrap items-end gap-3 mb-3">
              <label className="text-xs text-slate-600 dark:text-slate-300 flex flex-col">
                Filter by name
                <input
                  className="mt-1 border border-slate-300 dark:border-slate-700 dark:bg-slate-900 rounded px-2 py-1.5 text-sm"
                  value={filterText}
                  onChange={(e) => setFilterText(e.target.value)}
                  placeholder="search…"
                />
              </label>
              <label className="text-xs text-slate-600 dark:text-slate-300 flex flex-col">
                Sort
                <select
                  aria-label="Sort company health table"
                  className="mt-1 border border-slate-300 dark:border-slate-700 dark:bg-slate-900 rounded px-2 py-1.5 text-sm"
                  value={sortKey}
                  onChange={(e) => setSortKey(e.target.value as SortKey)}
                >
                  <option value="failures">Failures (desc)</option>
                  <option value="last_success">Last success (recent first)</option>
                  <option value="jobs_active">Active jobs (desc)</option>
                  <option value="name">Name (A–Z)</option>
                </select>
              </label>
              <div className="text-xs text-slate-500 dark:text-slate-400 ml-auto">
                <strong>{rows.length}</strong> shown
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50 dark:bg-slate-800/60 text-slate-600 dark:text-slate-300 text-xs uppercase">
                  <tr>
                    <th className="text-center px-3 py-2 font-medium" title="Toggle scraping (custom-selector companies)">
                      Scrape
                    </th>
                    <th className="text-left px-3 py-2 font-medium">Company</th>
                    <th className="text-left px-3 py-2 font-medium">ATS</th>
                    <th className="text-right px-3 py-2 font-medium">Active jobs</th>
                    <th className="text-right px-3 py-2 font-medium">Fails</th>
                    <th className="text-left px-3 py-2 font-medium">Last success</th>
                    <th className="text-left px-3 py-2 font-medium">Last scraped</th>
                    <th className="text-right px-3 py-2 font-medium">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {health.isLoading && (
                    <tr>
                      <td colSpan={8} className="text-center text-slate-400 py-6">
                        Loading…
                      </td>
                    </tr>
                  )}
                  {rows.length === 0 && !health.isLoading && (
                    <tr>
                      <td colSpan={8} className="text-center text-slate-400 py-6">
                        No companies match.
                      </td>
                    </tr>
                  )}
                  {rows.map((r) => (
                    <tr
                      key={r.id}
                      className={`border-t border-slate-100 dark:border-slate-800 ${!r.active ? "opacity-50" : ""}`}
                    >
                      <td className="px-3 py-2 text-center">
                        {r.has_selectors ? (
                          <label
                            className="inline-flex items-center gap-1.5 cursor-pointer"
                            title={
                              r.active
                                ? "Included in scrape runs — click to skip"
                                : "Skipped in scrape runs — click to include"
                            }
                          >
                            <input
                              type="checkbox"
                              className="h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-400"
                              checked={r.active}
                              disabled={
                                toggleScrape.isPending &&
                                toggleScrape.variables?.id === r.id
                              }
                              onChange={() =>
                                toggleScrape.mutate({ id: r.id, active: !r.active })
                              }
                              aria-label={`${r.active ? "Disable" : "Enable"} scraping for ${r.name}`}
                            />
                            <span className="text-[11px] text-slate-500 dark:text-slate-400">
                              {toggleScrape.isPending && toggleScrape.variables?.id === r.id
                                ? "…"
                                : r.active
                                ? "On"
                                : "Off"}
                            </span>
                          </label>
                        ) : (
                          <span
                            className="text-slate-300 dark:text-slate-600"
                            title="Not a custom-selector company"
                          >
                            —
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap font-medium text-slate-800 dark:text-slate-100">
                        {r.name}
                        {!r.active && (
                          <span className="ml-1 text-xs text-slate-400">(inactive)</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-slate-600 dark:text-slate-300">{r.ats_type}</td>
                      <td className="px-3 py-2 text-right text-slate-700 dark:text-slate-200">
                        {r.jobs_active}
                      </td>
                      <td
                        className={`px-3 py-2 text-right ${
                          r.consecutive_failures > 0
                            ? "text-red-700 dark:text-red-400 font-semibold"
                            : "text-slate-500 dark:text-slate-400"
                        }`}
                      >
                        {r.consecutive_failures}
                      </td>
                      <td className="px-3 py-2 text-slate-500 dark:text-slate-400">
                        {fmtAgo(r.last_success_at)}
                      </td>
                      <td className="px-3 py-2 text-slate-500 dark:text-slate-400">
                        {fmtAgo(r.last_scraped_at)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          type="button"
                          disabled={
                            !r.active ||
                            (scrape.isPending && scrape.variables === r.id)
                          }
                          onClick={() => scrape.mutate(r.id)}
                          className="text-xs border border-slate-300 dark:border-slate-700 rounded px-2 py-1 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50"
                          title={!r.active ? "Enable scraping first" : undefined}
                        >
                          {scrape.isPending && scrape.variables === r.id
                            ? "Queued…"
                            : "Scrape now"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {(scrape.isError || toggleScrape.isError) && (
              <div className="mt-2 text-xs text-red-700 dark:text-red-400">
                {scrape.isError && <>Trigger failed: {(scrape.error as Error).message}</>}
                {toggleScrape.isError && (
                  <>Toggle failed: {(toggleScrape.error as Error).message}</>
                )}
              </div>
            )}
          </div>
        )}
      </section>

      <section className={sectionCls}>
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">
          Recent scrape runs
        </h2>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-800/60 text-slate-600 dark:text-slate-300 text-xs uppercase">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Run</th>
                <th className="text-left px-3 py-2 font-medium">Started</th>
                <th className="text-left px-3 py-2 font-medium">Finished</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
                <th className="text-right px-3 py-2 font-medium">Companies</th>
                <th className="text-right px-3 py-2 font-medium">Found</th>
                <th className="text-right px-3 py-2 font-medium">New</th>
                <th className="text-left px-3 py-2 font-medium">Errors</th>
              </tr>
            </thead>
            <tbody>
              {(runs.data ?? []).length === 0 && (
                <tr>
                  <td colSpan={8} className="text-center text-slate-400 py-6">
                    No scrape runs recorded yet.
                  </td>
                </tr>
              )}
              {(runs.data ?? []).map((r: ScrapeRun) => (
                <tr key={r.id} className="border-t border-slate-100 dark:border-slate-800 align-top">
                  <td className="px-3 py-2 text-slate-500 dark:text-slate-400">#{r.id}</td>
                  <td className="px-3 py-2 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                    {fmtDateTime(r.started_at)}
                  </td>
                  <td className="px-3 py-2 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                    {fmtDateTime(r.finished_at)}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={
                        r.status === "ok"
                          ? "text-emerald-700 dark:text-emerald-400"
                          : r.status === "partial"
                          ? "text-amber-700 dark:text-amber-400"
                          : r.status === "running"
                          ? "text-slate-700 dark:text-slate-300"
                          : "text-red-700 dark:text-red-400"
                      }
                    >
                      {r.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right">{r.companies_scraped}</td>
                  <td className="px-3 py-2 text-right">{r.jobs_found_total}</td>
                  <td className="px-3 py-2 text-right font-semibold">{r.jobs_new_total}</td>
                  <td className="px-3 py-2 text-xs text-red-700 dark:text-red-400 whitespace-pre-wrap">
                    {r.error_summary ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
