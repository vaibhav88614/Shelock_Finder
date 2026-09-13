// Shared URL-state serializer.
//
// The dashboard's view / filter / page / density state is reflected into
// `window.location.search` so users can bookmark or share a query. The
// backend never sees this — we only mirror what already lives in local
// component state, so a full refresh reconstructs the exact same view.
//
// Numeric filter values are decoded loosely — bad values fall back to
// defaults rather than throwing, which keeps hand-edited URLs friendly.

import { defaultFilters, type JobFilters, type SortOption } from "./types";

export type View = "jobs" | "admin";
export type Density = "comfortable" | "compact" | "dense";

export interface UrlState {
  view: View;
  filters: JobFilters;
  page: number;
  pageSize: number;
  density: Density;
}

const VALID_SORTS: SortOption[] = [
  "posted_date",
  "company",
  "title",
  "first_seen",
  "match",
];
const VALID_DENSITIES: Density[] = ["comfortable", "compact", "dense"];

function toInt(v: string | null, fallback: number): number {
  if (!v) return fallback;
  const n = Number.parseInt(v, 10);
  return Number.isFinite(n) ? n : fallback;
}

function toIntOrNull(v: string | null): number | null {
  if (v === null || v === "") return null;
  const n = Number.parseInt(v, 10);
  return Number.isFinite(n) ? n : null;
}

function toFloatOrNull(v: string | null): number | null {
  if (v === null || v === "") return null;
  const n = Number.parseFloat(v);
  return Number.isFinite(n) ? n : null;
}

export function readUrlState(): UrlState {
  const p = new URLSearchParams(window.location.search);
  const d = defaultFilters();

  const rawView = p.get("view");
  const view: View = rawView === "admin" ? "admin" : "jobs";

  const rawSort = p.get("sort") as SortOption | null;
  const sort = rawSort && VALID_SORTS.includes(rawSort) ? rawSort : d.sort;

  const rawDensity = p.get("density") as Density | null;
  const density =
    rawDensity && VALID_DENSITIES.includes(rawDensity) ? rawDensity : "comfortable";

  const remoteParam = p.get("remote_only");
  const remoteOnly =
    remoteParam === null || remoteParam === ""
      ? null
      : remoteParam === "true" || remoteParam === "1";

  const filters: JobFilters = {
    keywords: p.getAll("keywords").flatMap((k) => k.split(",").map((s) => s.trim()).filter(Boolean)),
    keyword_logic: p.get("keyword_logic") === "and" ? "and" : "or",
    location: p.get("location") ?? "",
    cities: p.getAll("cities"),
    countries: p.getAll("countries"),
    regions: p.getAll("regions"),
    remote_only: remoteOnly,
    experience_min: toIntOrNull(p.get("experience_min")),
    experience_max: toIntOrNull(p.get("experience_max")),
    posted_within_days: toInt(p.get("posted_within_days"), d.posted_within_days),
    company_ids: p
      .getAll("company_ids")
      .map((v) => Number.parseInt(v, 10))
      .filter(Number.isFinite),
    sort,
    new_in_last_run: p.get("new_in_last_run") === "true",
    min_match_score: toFloatOrNull(p.get("min_match_score")),
  };

  return {
    view,
    filters,
    page: Math.max(1, toInt(p.get("page"), 1)),
    pageSize: Math.max(10, toInt(p.get("page_size"), 50)),
    density,
  };
}

export function writeUrlState(state: UrlState): void {
  const p = new URLSearchParams();
  const d = defaultFilters();
  const f = state.filters;

  if (state.view !== "jobs") p.set("view", state.view);
  for (const k of f.keywords) if (k) p.append("keywords", k);
  if (f.keyword_logic !== d.keyword_logic) p.set("keyword_logic", f.keyword_logic);
  if (f.location) p.set("location", f.location);
  for (const c of f.cities) p.append("cities", c);
  for (const c of f.countries) p.append("countries", c);
  for (const r of f.regions) p.append("regions", r);
  if (f.remote_only !== null) p.set("remote_only", String(f.remote_only));
  if (f.experience_min !== null) p.set("experience_min", String(f.experience_min));
  if (f.experience_max !== null) p.set("experience_max", String(f.experience_max));
  if (f.posted_within_days !== d.posted_within_days)
    p.set("posted_within_days", String(f.posted_within_days));
  for (const id of f.company_ids) p.append("company_ids", String(id));
  if (f.sort !== d.sort) p.set("sort", f.sort);
  if (f.new_in_last_run) p.set("new_in_last_run", "true");
  if (f.min_match_score !== null) p.set("min_match_score", String(f.min_match_score));

  if (state.page !== 1) p.set("page", String(state.page));
  if (state.pageSize !== 50) p.set("page_size", String(state.pageSize));
  if (state.density !== "comfortable") p.set("density", state.density);

  const qs = p.toString();
  const target = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
  if (target !== window.location.pathname + window.location.search) {
    window.history.replaceState(null, "", target);
  }
}
