// Typed mirrors of the backend Pydantic schemas. Hand-maintained: keep in
// sync with backend/api/schemas.py when fields change.

export interface Job {
  id: number;
  company_id: number;
  company_name: string | null;
  title: string;
  location: string | null;
  city: string | null;
  region: string | null;
  country: string | null;
  is_remote: boolean;
  remote_type: string | null;
  department: string | null;
  employment_type: string | null;
  experience_min: number | null;
  experience_max: number | null;
  posted_date: string | null;
  apply_url: string;
  description: string | null;
  first_seen_at: string;
  last_seen_at: string;
  is_active: boolean;
  keywords_matched: string[];
  match_score: number | null;
  matched_terms: string[];
}

export interface JobsListOut {
  items: Job[];
  next_cursor: string | null;
  total: number | null;
}

export interface Company {
  id: number;
  name: string;
  careers_url: string;
  ats_type: string;
  ats_identifier: string | null;
  custom_selectors: Record<string, unknown> | null;
  active: boolean;
  last_scraped_at: string | null;
  last_success_at: string | null;
  consecutive_failures: number;
  created_at: string;
}

export type ScrapeRunStatus = "running" | "ok" | "partial" | "failed";

export interface ScrapeRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: ScrapeRunStatus;
  companies_scraped: number;
  jobs_found_total: number;
  jobs_new_total: number;
  error_summary: string | null;
}

export interface CompanyHealth {
  id: number;
  name: string;
  ats_type: string;
  active: boolean;
  has_selectors: boolean;
  last_scraped_at: string | null;
  last_success_at: string | null;
  consecutive_failures: number;
  jobs_active: number;
}

export interface Stats {
  jobs_total: number;
  jobs_active: number;
  jobs_last_15d: number;
  companies_total: number;
  companies_active: number;
  last_run: ScrapeRun | null;
}

export interface DetectAtsResult {
  ats_type: string | null;
  ats_identifier: string | null;
  recognized: boolean;
}

export interface BulkImportResult {
  inserted: number;
  updated: number;
  skipped: number;
  errors: string[];
}

export interface BulkActiveResult {
  updated: number;
  matched: number;
}

export interface CleanupJobsResult {
  cutoff: string;
  matched: number;
  deleted: number;
  dry_run: boolean;
}

export type SortOption =
  | "posted_date"
  | "company"
  | "title"
  | "first_seen"
  | "match";
export type KeywordLogic = "and" | "or";

export interface JobFilters {
  keywords: string[];
  keyword_logic: KeywordLogic;
  location: string;
  cities: string[];
  countries: string[];
  regions: string[];
  remote_only: boolean | null;
  experience_min: number | null;
  experience_max: number | null;
  posted_within_days: number;
  company_ids: number[];
  sort: SortOption;
  new_in_last_run: boolean;
  min_match_score: number | null;
}

export const defaultFilters = (): JobFilters => ({
  keywords: [],
  keyword_logic: "or",
  location: "",
  cities: [],
  countries: [],
  regions: [],
  remote_only: null,
  experience_min: null,
  experience_max: null,
  posted_within_days: 15,
  company_ids: [],
  sort: "posted_date",
  new_in_last_run: false,
  min_match_score: null,
});

export interface LocationFacet {
  value: string;
  count: number;
  label: string | null;
}

export interface LocationFacetsOut {
  cities: LocationFacet[];
  countries: LocationFacet[];
  regions: LocationFacet[];
  remote: number;
  onsite: number;
}

export interface SparklinePoint {
  label: string;
  value: number;
}

export interface SparklinesOut {
  new_jobs_per_day: SparklinePoint[];
  active_per_day: SparklinePoint[];
  runs_jobs_new: SparklinePoint[];
  runs_jobs_found: SparklinePoint[];
}

export interface ResumeInfo {
  id: number;
  name: string;
  filename: string | null;
  uploaded_at: string;
  scored_at: string | null;
  text_length: number;
  bag_size: number;
  matches_total: number;
  matches_nonzero: number;
}

export interface RescoreResult {
  resume_id: number;
  scored: number;
  nonzero: number;
  top_score: number;
  duration_s: number;
}
