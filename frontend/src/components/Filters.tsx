import { memo, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchLocationFacets } from "../api";
import { defaultFilters, type JobFilters, type SortOption } from "../types";

interface Props {
  value: JobFilters;
  onChange: (next: JobFilters) => void;
  onExport: () => void;
  hasResume: boolean;
}

const BASE_SORTS: { label: string; value: SortOption }[] = [
  { label: "Posted date", value: "posted_date" },
  { label: "Company", value: "company" },
  { label: "Title", value: "title" },
  { label: "First seen", value: "first_seen" },
];

function eqStrList(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

// Deep-equal check for JobFilters — cheap at this size and prevents
// spurious "Apply" re-fires.
function filtersEqual(a: JobFilters, b: JobFilters): boolean {
  return (
    a.keywords.join("|") === b.keywords.join("|") &&
    a.keyword_logic === b.keyword_logic &&
    a.location === b.location &&
    eqStrList(a.cities, b.cities) &&
    eqStrList(a.countries, b.countries) &&
    eqStrList(a.regions, b.regions) &&
    a.remote_only === b.remote_only &&
    a.experience_min === b.experience_min &&
    a.experience_max === b.experience_max &&
    a.posted_within_days === b.posted_within_days &&
    a.company_ids.join(",") === b.company_ids.join(",") &&
    a.sort === b.sort &&
    a.new_in_last_run === b.new_in_last_run &&
    a.min_match_score === b.min_match_score
  );
}

interface ChipMultiProps {
  label: string;
  options: { value: string; count: number }[];
  selected: string[];
  onChange: (next: string[]) => void;
}

function ChipMulti({ label, options, selected, onChange }: ChipMultiProps) {
  if (options.length === 0) return null;
  const toggle = (v: string) => {
    if (selected.includes(v)) onChange(selected.filter((x) => x !== v));
    else onChange([...selected, v]);
  };
  return (
    <div className="text-xs text-slate-600 dark:text-slate-300">
      <div className="mb-1 flex items-center justify-between">
        <span>{label}</span>
        {selected.length > 0 && (
          <button
            type="button"
            className="text-[10px] text-slate-500 hover:text-slate-800 dark:hover:text-slate-100 underline underline-offset-2"
            onClick={() => onChange([])}
          >
            clear
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-1">
        {options.map((o) => {
          const on = selected.includes(o.value);
          return (
            <button
              type="button"
              key={o.value}
              onClick={() => toggle(o.value)}
              aria-pressed={on}
              className={`px-2 py-0.5 rounded-full border text-[11px] transition-colors ${
                on
                  ? "bg-slate-900 text-white border-slate-900 dark:bg-slate-100 dark:text-slate-900 dark:border-slate-100"
                  : "bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-200 border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"
              }`}
              title={`${o.value} · ${o.count.toLocaleString()} jobs`}
            >
              {o.value}
              <span className="ml-1 text-[10px] opacity-60">
                {o.count.toLocaleString()}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Filters panel — edits are held locally as a draft and only pushed up when
 * the user clicks "Apply filters" (or presses Enter in a text field). This
 * prevents the jobs list from thrashing on every keystroke and lets the user
 * see the pending state before committing.
 */
export const Filters = memo(function Filters({ value, onChange, onExport, hasResume }: Props) {
  const [draft, setDraft] = useState<JobFilters>(value);
  const [keywordText, setKeywordText] = useState(value.keywords.join(", "));

  useEffect(() => {
    setDraft(value);
    setKeywordText(value.keywords.join(", "));
  }, [value]);

  const facets = useQuery({
    queryKey: ["location-facets", draft.posted_within_days],
    queryFn: () => fetchLocationFacets(15, draft.posted_within_days),
    staleTime: 60_000,
  });

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

  const sortOptions: { label: string; value: SortOption }[] = hasResume
    ? [{ label: "Match score", value: "match" }, ...BASE_SORTS]
    : BASE_SORTS;

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
          Location (substring)
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
            {sortOptions.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {(facets.data?.countries?.length ?? 0) + (facets.data?.cities?.length ?? 0) > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-slate-200 dark:border-slate-800">
          <ChipMulti
            label="Country"
            options={(facets.data?.countries ?? []).map((c) => ({
              value: c.value,
              count: c.count,
            }))}
            selected={draft.countries}
            onChange={(next) => set("countries", next)}
          />
          <ChipMulti
            label="City"
            options={(facets.data?.cities ?? []).map((c) => ({
              value: c.value,
              count: c.count,
            }))}
            selected={draft.cities}
            onChange={(next) => set("cities", next)}
          />
        </div>
      )}

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
