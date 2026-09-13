import { memo, useMemo } from "react";
import type { Job } from "../types";
import type { Density } from "../urlState";

interface Props {
  jobs: Job[];
  onSelect: (job: Job) => void;
  loading: boolean;
  total: number | null;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  density: Density;
  onDensityChange: (density: Density) => void;
  showMatchColumn: boolean;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toISOString().slice(0, 10);
}

function fmtScore(n: number | null): string {
  if (n === null || n === undefined) return "—";
  return n.toFixed(1);
}

function buildPageList(current: number, totalPages: number): (number | "…")[] {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }
  const pages: (number | "…")[] = [1];
  const start = Math.max(2, current - 1);
  const end = Math.min(totalPages - 1, current + 1);
  if (start > 2) pages.push("…");
  for (let p = start; p <= end; p++) pages.push(p);
  if (end < totalPages - 1) pages.push("…");
  pages.push(totalPages);
  return pages;
}

const PAGE_SIZES = [25, 50, 100, 200];

const DENSITY_ROW: Record<Density, string> = {
  comfortable: "px-4 py-2",
  compact: "px-3 py-1.5",
  dense: "px-2 py-1",
};

const DENSITY_TEXT: Record<Density, string> = {
  comfortable: "text-sm",
  compact: "text-sm",
  dense: "text-xs",
};

export const JobTable = memo(function JobTable({
  jobs,
  onSelect,
  loading,
  total,
  page,
  pageSize,
  onPageChange,
  onPageSizeChange,
  density,
  onDensityChange,
  showMatchColumn,
}: Props) {
  const totalPages = useMemo(() => {
    if (total === null || total <= 0) return 1;
    return Math.max(1, Math.ceil(total / pageSize));
  }, [total, pageSize]);

  const clampedPage = Math.min(page, totalPages);
  const first = total === null ? 0 : total === 0 ? 0 : (clampedPage - 1) * pageSize + 1;
  const last = total === null ? jobs.length : Math.min(clampedPage * pageSize, total);
  const pageList = buildPageList(clampedPage, totalPages);

  const btn =
    "text-xs border border-slate-300 dark:border-slate-700 rounded px-2 py-1 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed";
  const cell = DENSITY_ROW[density];
  const textCls = DENSITY_TEXT[density];
  const colCount = showMatchColumn ? 7 : 6;

  return (
    <div
      className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg shadow-sm overflow-hidden"
      aria-busy={loading}
    >
      <div
        className="px-4 py-2 border-b border-slate-200 dark:border-slate-800 text-xs text-slate-500 dark:text-slate-400 flex justify-between items-center gap-3 flex-wrap"
        aria-live="polite"
        aria-atomic="true"
      >
        <span>
          {total !== null && total > 0
            ? `Showing ${first}–${last} of ${total.toLocaleString()}`
            : total === 0
            ? "0 results"
            : `${jobs.length} loaded`}
        </span>
        <span className="flex items-center gap-3">
          <label className="text-[11px] text-slate-500 dark:text-slate-400 flex items-center gap-1">
            Density
            <select
              value={density}
              onChange={(e) => onDensityChange(e.target.value as Density)}
              className="border border-slate-300 dark:border-slate-700 dark:bg-slate-900 rounded px-1.5 py-0.5 text-xs"
              title="Row height"
            >
              <option value="comfortable">Comfortable</option>
              <option value="compact">Compact</option>
              <option value="dense">Dense</option>
            </select>
          </label>
          <label className="text-[11px] text-slate-500 dark:text-slate-400 flex items-center gap-1">
            Per page
            <select
              value={pageSize}
              onChange={(e) => onPageSizeChange(Number(e.target.value))}
              className="border border-slate-300 dark:border-slate-700 dark:bg-slate-900 rounded px-1.5 py-0.5 text-xs"
            >
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <span>{loading ? "Loading…" : ""}</span>
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className={`min-w-full ${textCls}`}>
          <thead className="bg-slate-50 dark:bg-slate-800/60 text-slate-600 dark:text-slate-300 text-xs uppercase">
            <tr>
              {showMatchColumn && (
                <th className={`text-right ${cell} font-medium`}>Match</th>
              )}
              <th className={`text-left ${cell} font-medium`}>Company</th>
              <th className={`text-left ${cell} font-medium`}>Title</th>
              <th className={`text-left ${cell} font-medium`}>Location</th>
              <th className={`text-left ${cell} font-medium`}>Remote</th>
              <th className={`text-left ${cell} font-medium`}>Posted</th>
              <th className={`text-left ${cell} font-medium`}>Keywords</th>
            </tr>
          </thead>
          <tbody>
            {jobs.length === 0 && !loading && (
              <tr>
                <td colSpan={colCount} className="px-4 py-8 text-center text-slate-400">
                  No jobs match the current filters.
                </td>
              </tr>
            )}
            {jobs.map((j) => (
              <tr
                key={j.id}
                className="border-t border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50 cursor-pointer"
                onClick={() => onSelect(j)}
              >
                {showMatchColumn && (
                  <td className={`${cell} text-right`}>
                    {j.match_score !== null && j.match_score > 0 ? (
                      <span
                        className="inline-block bg-emerald-100 dark:bg-emerald-900/40 text-emerald-800 dark:text-emerald-300 rounded px-1.5 py-0.5 text-xs font-semibold"
                        title={
                          j.matched_terms.length
                            ? `Top terms: ${j.matched_terms.join(", ")}`
                            : "BM25 score against your resume"
                        }
                      >
                        {fmtScore(j.match_score)}
                      </span>
                    ) : (
                      <span className="text-slate-300 dark:text-slate-600">
                        {fmtScore(j.match_score)}
                      </span>
                    )}
                  </td>
                )}
                <td className={`${cell} whitespace-nowrap text-slate-700 dark:text-slate-200`}>
                  {j.company_name ?? `#${j.company_id}`}
                </td>
                <td className={`${cell} dark:text-slate-100`}>{j.title}</td>
                <td className={`${cell} text-slate-600 dark:text-slate-300`}>
                  {j.location ?? "—"}
                </td>
                <td className={`${cell} text-slate-500 dark:text-slate-400`}>
                  {j.is_remote ? "Remote" : j.remote_type ?? "—"}
                </td>
                <td className={`${cell} text-slate-500 dark:text-slate-400`}>
                  {fmtDate(j.posted_date)}
                </td>
                <td className={cell}>
                  <div className="flex flex-wrap gap-1">
                    {j.keywords_matched.map((k) => (
                      <span
                        key={k}
                        className="inline-block bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 text-xs rounded px-1.5 py-0.5"
                      >
                        {k}
                      </span>
                    ))}
                    {showMatchColumn &&
                      j.matched_terms.slice(0, 3).map((t) => (
                        <span
                          key={`m-${t}`}
                          className="inline-block bg-emerald-100 dark:bg-emerald-900/40 text-emerald-800 dark:text-emerald-300 text-xs rounded px-1.5 py-0.5"
                          title="matched resume term"
                        >
                          {t}
                        </span>
                      ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="border-t border-slate-200 dark:border-slate-800 px-3 py-2 flex items-center justify-between gap-2 flex-wrap">
          <span className="text-xs text-slate-500 dark:text-slate-400">
            Page {clampedPage} of {totalPages}
          </span>
          <div className="flex items-center gap-1 flex-wrap">
            <button
              type="button"
              className={btn}
              onClick={() => onPageChange(1)}
              disabled={clampedPage === 1 || loading}
              aria-label="First page"
            >
              «
            </button>
            <button
              type="button"
              className={btn}
              onClick={() => onPageChange(clampedPage - 1)}
              disabled={clampedPage === 1 || loading}
              aria-label="Previous page"
            >
              ‹ Prev
            </button>
            {pageList.map((p, i) =>
              p === "…" ? (
                <span key={`gap-${i}`} className="text-xs text-slate-400 px-1">
                  …
                </span>
              ) : (
                <button
                  key={p}
                  type="button"
                  onClick={() => onPageChange(p)}
                  disabled={loading}
                  aria-current={p === clampedPage ? "page" : undefined}
                  className={`text-xs rounded px-2 py-1 border ${
                    p === clampedPage
                      ? "bg-slate-900 text-white border-slate-900 dark:bg-slate-100 dark:text-slate-900 dark:border-slate-100"
                      : "border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"
                  } disabled:opacity-40 disabled:cursor-not-allowed`}
                >
                  {p}
                </button>
              )
            )}
            <button
              type="button"
              className={btn}
              onClick={() => onPageChange(clampedPage + 1)}
              disabled={clampedPage >= totalPages || loading}
              aria-label="Next page"
            >
              Next ›
            </button>
            <button
              type="button"
              className={btn}
              onClick={() => onPageChange(totalPages)}
              disabled={clampedPage >= totalPages || loading}
              aria-label="Last page"
            >
              »
            </button>
          </div>
        </div>
      )}
    </div>
  );
});
