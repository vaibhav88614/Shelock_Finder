import { memo, useEffect, useState } from "react";
import { defaultFilters, type JobFilters, type SortOption } from "../types";

interface Props {
  value: JobFilters;
  onChange: (next: JobFilters) => void;
  onExport: () => void;
}

const SORTS: { label: string; value: SortOption }[] = [
  { label: "Posted date", value: "posted_date" },
  { label: "Company", value: "company" },
  { label: "Title", value: "title" },
  { label: "First seen", value: "first_seen" },
];

// Deep-equal check for JobFilters — fine at this size (< 15 fields).
function filtersEqual(a: JobFilters, b: JobFilters): boolean {
  return (
    a.keywords.join("|") === b.keywords.join("|") &&
    a.keyword_logic === b.keyword_logic &&
    a.location === b.location &&
    a.remote_only === b.remote_only &&
    a.experience_min === b.experience_min &&
    a.experience_max === b.experience_max &&
    a.posted_within_days === b.posted_within_days &&
    a.company_ids.join(",") === b.company_ids.join(",") &&
    a.sort === b.sort &&
    a.new_in_last_run === b.new_in_last_run
  );
}

/**
 * Filters panel — edits are held locally as a draft and only pushed up when
 * the user clicks "Apply filters" (or presses Enter in a text field). This
 * prevents the jobs list from thrashing on every keystroke and lets the user
 * see the pending state before committing.
 */
export const Filters = memo(function Filters({ value, onChange, onExport }: Props) {
  const [draft, setDraft] = useState<JobFilters>(value);
  const [keywordText, setKeywordText] = useState(value.keywords.join(", "));

  // When the parent state changes (e.g. reset from elsewhere) sync the draft.
  useEffect(() => {
    setDraft(value);
    setKeywordText(value.keywords.join(", "));
  }, [value]);

  const parseKeywords = (text: string): string[] =>
    text
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

  const currentDraft = (): JobFilters => ({
    ...draft,
    keywords: parseKeywords(keywordText),
  });

  const set = <K extends keyof JobFilters>(k: K, v: JobFilters[K]) =>
    setDraft((prev) => ({ ...prev, [k]: v }));

  const apply = () => {
    const next = currentDraft();
    if (!filtersEqual(next, value)) onChange(next);
  };

  const reset = () => {
    const d = defaultFilters();
    setDraft(d);
    setKeywordText("");
    if (!filtersEqual(d, value)) onChange(d);
  };

  const submitOnEnter = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      apply();
    }
  };

  const isDirty = !filtersEqual(currentDraft(), value);

  const inputCls =
    "border border-slate-300 dark:border-slate-700 dark:bg-slate-900 rounded px-2 py-1.5 text-sm mt-1";
  const labelCls = "text-xs text-slate-600 dark:text-slate-300 flex flex-col";

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg p-4 space-y-3 shadow-sm">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        <label className={labelCls}>
          Keywords <span className="text-[10px] text-slate-400">comma-separated</span>
          <input
            className={inputCls}
            placeholder="python, kubernetes"
            value={keywordText}
            onChange={(e) => setKeywordText(e.target.value)}
            onKeyDown={submitOnEnter}
          />
        </label>
        <label className={labelCls}>
          Location
          <input
            className={inputCls}
            placeholder="Berlin, Remote, US…"
            value={draft.location}
            onChange={(e) => set("location", e.target.value)}
            onKeyDown={submitOnEnter}
          />
        </label>
        <label className={labelCls}>
          Keyword logic
          <select
            className={inputCls}
            value={draft.keyword_logic}
            onChange={(e) => set("keyword_logic", e.target.value as "and" | "or")}
          >
            <option value="or">OR (any keyword)</option>
            <option value="and">AND (all keywords)</option>
          </select>
        </label>
        <label className={labelCls}>
          Sort
          <select
            className={inputCls}
            value={draft.sort}
            onChange={(e) => set("sort", e.target.value as SortOption)}
          >
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 items-end">
        <label className={labelCls}>
          Posted within (days)
          <input
            type="number"
            min={1}
            max={15}
            className={inputCls}
            value={draft.posted_within_days}
            onChange={(e) =>
              set(
                "posted_within_days",
                Math.max(1, Math.min(15, Number(e.target.value) || 15))
              )
            }
            onKeyDown={submitOnEnter}
          />
        </label>
        <label className={labelCls}>
          Exp. min (yrs)
          <input
            type="number"
            min={0}
            max={30}
            className={inputCls}
            value={draft.experience_min ?? ""}
            onChange={(e) =>
              set(
                "experience_min",
                e.target.value === "" ? null : Number(e.target.value)
              )
            }
            onKeyDown={submitOnEnter}
          />
        </label>
        <label className={labelCls}>
          Exp. max (yrs)
          <input
            type="number"
            min={0}
            max={30}
            className={inputCls}
            value={draft.experience_max ?? ""}
            onChange={(e) =>
              set(
                "experience_max",
                e.target.value === "" ? null : Number(e.target.value)
              )
            }
            onKeyDown={submitOnEnter}
          />
        </label>
        <label className={labelCls}>
          Remote
          <select
            className={inputCls}
            value={draft.remote_only === null ? "" : draft.remote_only ? "yes" : "no"}
            onChange={(e) => {
              const v = e.target.value;
              set("remote_only", v === "" ? null : v === "yes");
            }}
          >
            <option value="">Any</option>
            <option value="yes">Remote only</option>
            <option value="no">On-site / hybrid</option>
          </select>
        </label>
        <label className="text-xs text-slate-600 dark:text-slate-300 flex items-center gap-2 mt-4">
          <input
            type="checkbox"
            checked={draft.new_in_last_run}
            onChange={(e) => set("new_in_last_run", e.target.checked)}
          />
          New in last run
        </label>
        <div className="flex items-center gap-2 justify-end">
          <button
            type="button"
            onClick={reset}
            className="text-xs border border-slate-300 dark:border-slate-700 rounded px-3 py-1.5 hover:bg-slate-100 dark:hover:bg-slate-800"
            title="Reset all filters to defaults"
          >
            Reset
          </button>
          <button
            type="button"
            onClick={apply}
            disabled={!isDirty}
            className="text-sm bg-slate-900 text-white rounded px-3 py-1.5 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
            title="Apply pending filter changes"
          >
            {isDirty ? "Apply filters" : "Filters applied"}
          </button>
          <button
            type="button"
            onClick={onExport}
            className="text-sm border border-slate-300 dark:border-slate-700 rounded px-3 py-1.5 hover:bg-slate-100 dark:hover:bg-slate-800"
            title="Download the current results as CSV"
          >
            Export CSV
          </button>
        </div>
      </div>
      {isDirty && (
        <p className="text-[11px] text-amber-700 dark:text-amber-400">
          Pending changes — click <strong>Apply filters</strong> (or press Enter) to update the results.
        </p>
      )}
    </div>
  );
});
