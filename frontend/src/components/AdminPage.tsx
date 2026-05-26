import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchCompanyHealth, fetchRuns, triggerScrape } from "../api";
import type { CompanyHealth, ScrapeRun } from "../types";

type SortKey = "failures" | "name" | "last_success" | "jobs_active";

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

export function AdminPage() {
  const qc = useQueryClient();
  const [sortKey, setSortKey] = useState<SortKey>("failures");
  const [filterText, setFilterText] = useState("");

  const health = useQuery({ queryKey: ["company-health"], queryFn: fetchCompanyHealth });
  const runs = useQuery({ queryKey: ["runs", "admin"], queryFn: () => fetchRuns(25) });

  const scrape = useMutation({
    mutationFn: (id: number) => triggerScrape(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["company-health"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const rows = sortHealth(health.data ?? [], sortKey).filter((r) =>
    !filterText ? true : r.name.toLowerCase().includes(filterText.toLowerCase())
  );

  const failing = (health.data ?? []).filter((r) => r.consecutive_failures > 0).length;
  const inactive = (health.data ?? []).filter((r) => !r.active).length;

  return (
    <div className="space-y-5">
      <section className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-700 mb-3">Per-company health</h2>
        <div className="flex flex-wrap items-end gap-3 mb-3">
          <label className="text-xs text-slate-600 flex flex-col">
            Filter by name
            <input
              className="mt-1 border border-slate-300 rounded px-2 py-1.5 text-sm"
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              placeholder="search…"
            />
          </label>
          <label className="text-xs text-slate-600 flex flex-col">
            Sort
            <select
              className="mt-1 border border-slate-300 rounded px-2 py-1.5 text-sm"
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
            >
              <option value="failures">Failures (desc)</option>
              <option value="last_success">Last success (recent first)</option>
              <option value="jobs_active">Active jobs (desc)</option>
              <option value="name">Name (A–Z)</option>
            </select>
          </label>
          <div className="text-xs text-slate-500 ml-auto">
            <strong>{rows.length}</strong> shown · <strong>{failing}</strong> failing ·{" "}
            <strong>{inactive}</strong> inactive
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
              <tr>
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
                  <td colSpan={7} className="text-center text-slate-400 py-6">
                    Loading…
                  </td>
                </tr>
              )}
              {rows.length === 0 && !health.isLoading && (
                <tr>
                  <td colSpan={7} className="text-center text-slate-400 py-6">
                    No companies match.
                  </td>
                </tr>
              )}
              {rows.map((r) => (
                <tr
                  key={r.id}
                  className={`border-t border-slate-100 ${!r.active ? "opacity-50" : ""}`}
                >
                  <td className="px-3 py-2 whitespace-nowrap font-medium text-slate-800">
                    {r.name}
                    {!r.active && <span className="ml-1 text-xs text-slate-400">(inactive)</span>}
                  </td>
                  <td className="px-3 py-2 text-slate-600">{r.ats_type}</td>
                  <td className="px-3 py-2 text-right text-slate-700">{r.jobs_active}</td>
                  <td
                    className={`px-3 py-2 text-right ${
                      r.consecutive_failures > 0 ? "text-red-700 font-semibold" : "text-slate-500"
                    }`}
                  >
                    {r.consecutive_failures}
                  </td>
                  <td className="px-3 py-2 text-slate-500">{fmtAgo(r.last_success_at)}</td>
                  <td className="px-3 py-2 text-slate-500">{fmtAgo(r.last_scraped_at)}</td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      disabled={scrape.isPending && scrape.variables === r.id}
                      onClick={() => scrape.mutate(r.id)}
                      className="text-xs border border-slate-300 rounded px-2 py-1 hover:bg-slate-100 disabled:opacity-50"
                    >
                      {scrape.isPending && scrape.variables === r.id ? "Queued…" : "Scrape now"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {scrape.isError && (
          <div className="mt-2 text-xs text-red-700">
            Trigger failed: {(scrape.error as Error).message}
          </div>
        )}
      </section>

      <section className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-700 mb-3">Recent scrape runs</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
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
                <tr key={r.id} className="border-t border-slate-100 align-top">
                  <td className="px-3 py-2 text-slate-500">#{r.id}</td>
                  <td className="px-3 py-2 text-slate-500 whitespace-nowrap">
                    {fmtDateTime(r.started_at)}
                  </td>
                  <td className="px-3 py-2 text-slate-500 whitespace-nowrap">
                    {fmtDateTime(r.finished_at)}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={
                        r.status === "success"
                          ? "text-emerald-700"
                          : r.status === "running"
                          ? "text-slate-700"
                          : "text-red-700"
                      }
                    >
                      {r.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right">{r.companies_scraped}</td>
                  <td className="px-3 py-2 text-right">{r.jobs_found_total}</td>
                  <td className="px-3 py-2 text-right font-semibold">{r.jobs_new_total}</td>
                  <td className="px-3 py-2 text-xs text-red-700 whitespace-pre-wrap">
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
