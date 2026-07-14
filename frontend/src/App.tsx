import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { AddCompanyModal } from "./components/AddCompanyModal";
import { AdminPage } from "./components/AdminPage";
import { Filters } from "./components/Filters";
import { JobDrawer } from "./components/JobDrawer";
import { JobTable } from "./components/JobTable";
import { StatsBar } from "./components/StatsBar";
import {
  downloadJobsCsv,
  fetchJobsPage,
  fetchRuns,
  fetchStats,
} from "./api";
import { applyTheme, getEffectiveTheme, saveTheme, type Theme } from "./theme";
import { defaultFilters, type Job, type JobFilters } from "./types";

type View = "jobs" | "admin";

const DEFAULT_PAGE_SIZE = 50;

export default function App() {
  const [view, setView] = useState<View>("jobs");
  const [filters, setFilters] = useState<JobFilters>(defaultFilters());
  const [selected, setSelected] = useState<Job | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  const [theme, setTheme] = useState<Theme>(() => getEffectiveTheme());
  useEffect(() => {
    applyTheme(theme);
    saveTheme(theme);
  }, [theme]);

  const stats = useQuery({ queryKey: ["stats"], queryFn: fetchStats });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => fetchRuns(5) });

  // Reset to page 1 whenever the filter set changes so users don't land on a
  // page number that no longer exists after tightening filters (e.g. jumping
  // from p10 → 5 total pages).
  useEffect(() => {
    setPage(1);
  }, [filters]);

  const jobs = useQuery({
    queryKey: [
      "jobs",
      page,
      pageSize,
      filters.keywords.join(","),
      filters.keyword_logic,
      filters.location,
      filters.remote_only,
      filters.experience_min,
      filters.experience_max,
      filters.posted_within_days,
      filters.sort,
      filters.new_in_last_run,
      filters.company_ids.join(","),
    ],
    queryFn: () =>
      fetchJobsPage(filters, (page - 1) * pageSize, pageSize, true),
    enabled: view === "jobs",
    // Keep previous page visible while the next one loads so the layout
    // doesn't jump around.
    placeholderData: (prev) => prev,
  });

  const flatJobs: Job[] = jobs.data?.items ?? [];
  const total = jobs.data?.total ?? null;

  const csvExport = useMutation({
    mutationFn: () => downloadJobsCsv(filters),
  });
  const handleExport = useCallback(() => {
    csvExport.mutate();
  }, [csvExport]);
  const handleAddClose = useCallback(() => setAddOpen(false), []);
  const handleDrawerClose = useCallback(() => setSelected(null), []);

  const handlePageChange = useCallback(
    (p: number) => {
      setPage(p);
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
    []
  );
  const handlePageSizeChange = useCallback((s: number) => {
    setPageSize(s);
    setPage(1);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  const themeIcon = useMemo(() => (theme === "dark" ? "☀︎" : "☾"), [theme]);

  return (
    <div className="min-h-full">
      <header className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100">JobPulse</h1>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Local job aggregator · 100% offline · no Docker
            </p>
          </div>
          <div className="flex items-center gap-3">
            <nav className="flex items-center gap-1 mr-2 bg-slate-100 dark:bg-slate-800 rounded p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setView("jobs")}
                className={`px-3 py-1 rounded ${
                  view === "jobs"
                    ? "bg-white dark:bg-slate-900 shadow text-slate-900 dark:text-slate-100"
                    : "text-slate-600 dark:text-slate-300"
                }`}
              >
                Jobs
              </button>
              <button
                type="button"
                onClick={() => setView("admin")}
                className={`px-3 py-1 rounded ${
                  view === "admin"
                    ? "bg-white dark:bg-slate-900 shadow text-slate-900 dark:text-slate-100"
                    : "text-slate-600 dark:text-slate-300"
                }`}
              >
                Admin
              </button>
            </nav>
            <button
              type="button"
              onClick={toggleTheme}
              className="text-sm border border-slate-300 dark:border-slate-700 rounded px-2 py-1 hover:bg-slate-100 dark:hover:bg-slate-800"
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            >
              <span aria-hidden>{themeIcon}</span>
              <span className="sr-only">Toggle theme</span>
            </button>
            <button
              type="button"
              onClick={() => setAddOpen(true)}
              className="text-sm bg-slate-900 text-white rounded px-3 py-1.5 hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
            >
              + Add company
            </button>
            {import.meta.env.DEV && (
              <a
                href="/health"
                target="_blank"
                rel="noreferrer"
                className="text-xs text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
              >
                /health
              </a>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-5 space-y-5">
        {view === "jobs" ? (
          <>
            <StatsBar stats={stats.data} runs={runs.data} />

            <Filters value={filters} onChange={setFilters} onExport={handleExport} />

            {jobs.isError && (
              <div className="bg-red-50 border border-red-200 text-red-800 rounded p-3 text-sm dark:bg-red-950/40 dark:border-red-900 dark:text-red-300">
                Failed to load jobs: {(jobs.error as Error).message}
              </div>
            )}
            {csvExport.isError && (
              <div
                className="bg-red-50 border border-red-200 text-red-800 rounded p-3 text-sm dark:bg-red-950/40 dark:border-red-900 dark:text-red-300"
                aria-live="polite"
              >
                CSV export failed: {(csvExport.error as Error).message}
              </div>
            )}

            <JobTable
              jobs={flatJobs}
              onSelect={setSelected}
              loading={jobs.isFetching}
              total={total}
              page={page}
              pageSize={pageSize}
              onPageChange={handlePageChange}
              onPageSizeChange={handlePageSizeChange}
            />
          </>
        ) : (
          <AdminPage />
        )}
      </main>

      <JobDrawer job={selected} onClose={handleDrawerClose} />
      {addOpen && <AddCompanyModal onClose={handleAddClose} />}
    </div>
  );
}
