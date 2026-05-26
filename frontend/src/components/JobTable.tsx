import type { Job } from "../types";

interface Props {
  jobs: Job[];
  onSelect: (job: Job) => void;
  loading: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
  total: number | null;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toISOString().slice(0, 10);
}

export function JobTable({ jobs, onSelect, loading, hasMore, onLoadMore, total }: Props) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden">
      <div className="px-4 py-2 border-b border-slate-200 text-xs text-slate-500 flex justify-between">
        <span>
          {jobs.length} loaded{total !== null ? ` / ${total} matching` : ""}
        </span>
        <span>{loading ? "Loading…" : ""}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-2 font-medium">Company</th>
              <th className="text-left px-4 py-2 font-medium">Title</th>
              <th className="text-left px-4 py-2 font-medium">Location</th>
              <th className="text-left px-4 py-2 font-medium">Remote</th>
              <th className="text-left px-4 py-2 font-medium">Posted</th>
              <th className="text-left px-4 py-2 font-medium">Keywords</th>
            </tr>
          </thead>
          <tbody>
            {jobs.length === 0 && !loading && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-slate-400">
                  No jobs match the current filters.
                </td>
              </tr>
            )}
            {jobs.map((j) => (
              <tr
                key={j.id}
                className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                onClick={() => onSelect(j)}
              >
                <td className="px-4 py-2 whitespace-nowrap text-slate-700">
                  {j.company_name ?? `#${j.company_id}`}
                </td>
                <td className="px-4 py-2">{j.title}</td>
                <td className="px-4 py-2 text-slate-600">{j.location ?? "—"}</td>
                <td className="px-4 py-2 text-slate-500">{j.remote_type ?? "—"}</td>
                <td className="px-4 py-2 text-slate-500">{fmtDate(j.posted_date)}</td>
                <td className="px-4 py-2">
                  <div className="flex flex-wrap gap-1">
                    {j.keywords_matched.map((k) => (
                      <span
                        key={k}
                        className="inline-block bg-amber-100 text-amber-800 text-xs rounded px-1.5 py-0.5"
                      >
                        {k}
                      </span>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hasMore && (
        <div className="border-t border-slate-200 p-3 text-center">
          <button
            type="button"
            onClick={onLoadMore}
            disabled={loading}
            className="text-sm border border-slate-300 rounded px-3 py-1.5 hover:bg-slate-100 disabled:opacity-50"
          >
            {loading ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}
