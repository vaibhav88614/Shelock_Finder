import { memo, useEffect, useRef, useState } from "react";
import type { JobFilters, SortOption } from "../types";

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

// Local debounced state so typing in keyword/location doesn't refetch on
// every keystroke. We propagate up after 300ms of inactivity.
export const Filters = memo(function Filters({ value, onChange, onExport }: Props) {
  const [keywordText, setKeywordText] = useState(value.keywords.join(", "));
  const [location, setLocation] = useState(value.location);

  // Refs let the debounced timeout read the *current* filter snapshot without
  // listing `value` / `onChange` as deps (which would reset the timer on
  // every parent re-render). Closure-stale bugs are why this exists.
  const valueRef = useRef(value);
  const onChangeRef = useRef(onChange);
  valueRef.current = value;
  onChangeRef.current = onChange;

  useEffect(() => {
    const t = setTimeout(() => {
      const v = valueRef.current;
      const kws = keywordText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      if (
        kws.join("|") !== v.keywords.join("|") ||
        location !== v.location
      ) {
        onChangeRef.current({ ...v, keywords: kws, location });
      }
    }, 300);
    return () => clearTimeout(t);
  }, [keywordText, location]);

  const set = <K extends keyof JobFilters>(k: K, v: JobFilters[K]) =>
    onChange({ ...value, [k]: v });

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3 shadow-sm">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        <label className="text-xs text-slate-600 flex flex-col">
          Keywords <span className="text-[10px] text-slate-400">comma-separated</span>
          <input
            className="border border-slate-300 rounded px-2 py-1.5 text-sm mt-1"
            placeholder="python, kubernetes"
            value={keywordText}
            onChange={(e) => setKeywordText(e.target.value)}
          />
        </label>
        <label className="text-xs text-slate-600 flex flex-col">
          Location
          <input
            className="border border-slate-300 rounded px-2 py-1.5 text-sm mt-1"
            placeholder="Berlin, Remote, US…"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
          />
        </label>
        <label className="text-xs text-slate-600 flex flex-col">
          Keyword logic
          <select
            className="border border-slate-300 rounded px-2 py-1.5 text-sm mt-1"
            value={value.keyword_logic}
            onChange={(e) => set("keyword_logic", e.target.value as "and" | "or")}
          >
            <option value="or">OR (any keyword)</option>
            <option value="and">AND (all keywords)</option>
          </select>
        </label>
        <label className="text-xs text-slate-600 flex flex-col">
          Sort
          <select
            className="border border-slate-300 rounded px-2 py-1.5 text-sm mt-1"
            value={value.sort}
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
        <label className="text-xs text-slate-600 flex flex-col">
          Posted within (days)
          <input
            type="number"
            min={1}
            max={15}
            className="border border-slate-300 rounded px-2 py-1.5 text-sm mt-1"
            value={value.posted_within_days}
            onChange={(e) =>
              set("posted_within_days", Math.max(1, Math.min(15, Number(e.target.value) || 15)))
            }
          />
        </label>
        <label className="text-xs text-slate-600 flex flex-col">
          Exp. min (yrs)
          <input
            type="number"
            min={0}
            max={30}
            className="border border-slate-300 rounded px-2 py-1.5 text-sm mt-1"
            value={value.experience_min ?? ""}
            onChange={(e) =>
              set("experience_min", e.target.value === "" ? null : Number(e.target.value))
            }
          />
        </label>
        <label className="text-xs text-slate-600 flex flex-col">
          Exp. max (yrs)
          <input
            type="number"
            min={0}
            max={30}
            className="border border-slate-300 rounded px-2 py-1.5 text-sm mt-1"
            value={value.experience_max ?? ""}
            onChange={(e) =>
              set("experience_max", e.target.value === "" ? null : Number(e.target.value))
            }
          />
        </label>
        <label className="text-xs text-slate-600 flex flex-col">
          Remote
          <select
            className="border border-slate-300 rounded px-2 py-1.5 text-sm mt-1"
            value={value.remote_only === null ? "" : value.remote_only ? "yes" : "no"}
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
        <label className="text-xs text-slate-600 flex items-center gap-2 mt-4">
          <input
            type="checkbox"
            checked={value.new_in_last_run}
            onChange={(e) => set("new_in_last_run", e.target.checked)}
          />
          New in last run
        </label>
        <button
          type="button"
          onClick={onExport}
          className="bg-slate-900 text-white text-sm rounded px-3 py-1.5 hover:bg-slate-700"
        >
          Export CSV
        </button>
      </div>
    </div>
  );
});
