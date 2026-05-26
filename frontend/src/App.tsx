import { useMemo, useState } from "react";
import { useQuery, useInfiniteQuery } from "@tanstack/react-query";
import { AddCompanyModal } from "./components/AddCompanyModal";
import { AdminPage } from "./components/AdminPage";
import { Filters } from "./components/Filters";
import { JobDrawer } from "./components/JobDrawer";
import { JobTable } from "./components/JobTable";
import { StatsBar } from "./components/StatsBar";
import { exportCsvUrl, fetchJobs, fetchRuns, fetchStats } from "./api";
import { defaultFilters, type Job, type JobFilters } from "./types";

type View = "jobs" | "admin";

export default function App() {
  const [view, setView] = useState<View>("jobs");
  const [filters, setFilters] = useState<JobFilters>(defaultFilters());
  const [selected, setSelected] = useState<Job | null>(null);
  const [addOpen, setAddOpen] = useState(false);

  const stats = useQuery({ queryKey: ["stats"], queryFn: fetchStats });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => fetchRuns(5) });

  const jobs = useInfiniteQuery({
    queryKey: ["jobs", filters],
    queryFn: ({ pageParam }) => fetchJobs(filters, pageParam as string | null, 50, true),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled: view === "jobs",
  });

  const flatJobs: Job[] = useMemo(
    () => (jobs.data?.pages ?? []).flatMap((p) => p.items),
    [jobs.data]
  );
  const total = jobs.data?.pages?.[0]?.total ?? null;

  return (
    <div className="min-h-full">
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-900">JobPulse</h1>
            <p className="text-xs text-slate-500">Local job aggregator · 100% offline · no Docker</p>
          </div>
          <div className="flex items-center gap-3">
            <nav className="flex items-center gap-1 mr-2 bg-slate-100 rounded p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setView("jobs")}
                className={`px-3 py-1 rounded ${
                  view === "jobs" ? "bg-white shadow text-slate-900" : "text-slate-600"
                }`}
              >
                Jobs
              </button>
              <button
                type="button"
                onClick={() => setView("admin")}
                className={`px-3 py-1 rounded ${
                  view === "admin" ? "bg-white shadow text-slate-900" : "text-slate-600"
                }`}
              >
                Admin
              </button>
            </nav>
            <button
              type="button"
              onClick={() => setAddOpen(true)}
              className="text-sm bg-slate-900 text-white rounded px-3 py-1.5 hover:bg-slate-700"
            >
              + Add company
            </button>
            <a
              href="/health"
              target="_blank"
              rel="noreferrer"
              className="text-xs text-slate-500 hover:text-slate-900"
            >
              /health
            </a>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-5 space-y-5">
        {view === "jobs" ? (
          <>
            <StatsBar stats={stats.data} runs={runs.data} />

            <Filters
              value={filters}
              onChange={setFilters}
              onExport={() => {
                window.location.href = exportCsvUrl(filters);
              }}
            />

            {jobs.isError && (
              <div className="bg-red-50 border border-red-200 text-red-800 rounded p-3 text-sm">
                Failed to load jobs: {(jobs.error as Error).message}
              </div>
            )}

            <JobTable
              jobs={flatJobs}
              onSelect={setSelected}
              loading={jobs.isFetching}
              hasMore={Boolean(jobs.hasNextPage)}
              onLoadMore={() => jobs.fetchNextPage()}
              total={total}
            />
          </>
        ) : (
          <AdminPage />
        )}
      </main>

      <JobDrawer job={selected} onClose={() => setSelected(null)} />
      {addOpen && <AddCompanyModal onClose={() => setAddOpen(false)} />}
    </div>
  );
}
