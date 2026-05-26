import type {
  BulkImportResult,
  Company,
  CompanyHealth,
  DetectAtsResult,
  JobFilters,
  JobsListOut,
  ScrapeRun,
  Stats,
} from "./types";

const API = "/api/v1";

function buildJobParams(filters: JobFilters, extra: Record<string, string> = {}): URLSearchParams {
  const p = new URLSearchParams();
  for (const k of filters.keywords) if (k.trim()) p.append("keywords", k.trim());
  p.set("keyword_logic", filters.keyword_logic);
  if (filters.location.trim()) p.set("location", filters.location.trim());
  if (filters.remote_only !== null) p.set("remote_only", String(filters.remote_only));
  if (filters.experience_min !== null) p.set("experience_min", String(filters.experience_min));
  if (filters.experience_max !== null) p.set("experience_max", String(filters.experience_max));
  p.set("posted_within_days", String(filters.posted_within_days));
  for (const id of filters.company_ids) p.append("company_ids", String(id));
  p.set("sort", filters.sort);
  if (filters.new_in_last_run) p.set("new_in_last_run", "true");
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  return p;
}

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${url}`);
  return (await r.json()) as T;
}

export async function fetchJobs(
  filters: JobFilters,
  cursor: string | null,
  limit = 50,
  includeTotal = false
): Promise<JobsListOut> {
  const p = buildJobParams(filters, { limit: String(limit) });
  if (cursor) p.set("cursor", cursor);
  if (includeTotal) p.set("include_total", "true");
  return getJson<JobsListOut>(`${API}/jobs?${p.toString()}`);
}

export function exportCsvUrl(filters: JobFilters): string {
  return `${API}/jobs/export.csv?${buildJobParams(filters).toString()}`;
}

export const fetchStats = () => getJson<Stats>(`${API}/stats`);
export const fetchCompanies = () => getJson<Company[]>(`${API}/companies`);
export const fetchRuns = (limit = 5) => getJson<ScrapeRun[]>(`${API}/scrape-runs?limit=${limit}`);
export const fetchCompanyHealth = () => getJson<CompanyHealth[]>(`${API}/stats/companies`);

export async function triggerScrape(companyId: number): Promise<void> {
  const r = await fetch(`${API}/companies/${companyId}/scrape`, { method: "POST" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
}

export const detectAts = (url: string) =>
  getJson<DetectAtsResult>(`${API}/companies/detect?url=${encodeURIComponent(url)}`);

export interface CreateCompanyPayload {
  name: string;
  careers_url: string;
  ats_type?: string | null;
  ats_identifier?: string | null;
  custom_selectors?: Record<string, unknown> | null;
}

export async function createCompany(payload: CreateCompanyPayload): Promise<Company> {
  const r = await fetch(`${API}/companies`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await r.json()) as Company;
}

export async function bulkImportCompanies(file: File): Promise<BulkImportResult> {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch(`${API}/companies/bulk-import`, { method: "POST", body: form });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as BulkImportResult;
}
