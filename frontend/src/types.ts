// Typed mirrors of the backend Pydantic schemas. Hand-maintained: keep in
// sync with backend/api/schemas.py when fields change.

export interface Job {
  id: number;
  company_id: number;
  company_name: string | null;
  title: string;
  location: string | null;
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

export interface ScrapeRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
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

export type SortOption = "posted_date" | "company" | "title" | "first_seen";
export type KeywordLogic = "and" | "or";

export interface JobFilters {
  keywords: string[];
  keyword_logic: KeywordLogic;
  location: string;
  remote_only: boolean | null;
  experience_min: number | null;
  experience_max: number | null;
  posted_within_days: number;
  company_ids: number[];
  sort: SortOption;
  new_in_last_run: boolean;
}

export const defaultFilters = (): JobFilters => ({
  keywords: [],
  keyword_logic: "or",
  location: "",
  remote_only: null,
  experience_min: null,
  experience_max: null,
  posted_within_days: 15,
  company_ids: [],
  sort: "posted_date",
  new_in_last_run: false,
});
