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

const API = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1";

// --- API key handling ----------------------------------------------------
// The backend requires X-API-Key on mutating endpoints when JOBPULSE_API_KEY
// is set on the server. We read from localStorage first (user-settable via the
// admin settings panel), then fall back to a Vite build-time env var.
const API_KEY_STORAGE_KEY = "jobpulse_api_key";

export function getApiKey(): string | null {
  try {
    const stored = localStorage.getItem(API_KEY_STORAGE_KEY);
    if (stored) return stored;
  } catch {
    /* localStorage unavailable */
  }
  const fromEnv = (import.meta.env.VITE_API_KEY as string | undefined) ?? null;
  return fromEnv && fromEnv.length > 0 ? fromEnv : null;
}

export function setApiKey(key: string): void {
  const trimmed = key.trim();
  if (!trimmed) {
    clearApiKey();
    return;
  }
  try {
    localStorage.setItem(API_KEY_STORAGE_KEY, trimmed);
  } catch {
    /* ignore */
  }
}

export function clearApiKey(): void {
  try {
    localStorage.removeItem(API_KEY_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

function mutateHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  const key = getApiKey();
  if (key) headers["X-API-Key"] = key;
  return headers;
}

async function readErrorMessage(r: Response): Promise<string> {
  let msg = `${r.status} ${r.statusText}`;
  try {
    const body = await r.json();
    if (body?.detail) {
      const detail =
        typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      msg = `${r.status}: ${detail}`;
    }
  } catch {
    /* ignore */
  }
  return msg;
}

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

export async function downloadJobsCsv(filters: JobFilters): Promise<void> {
  const url = exportCsvUrl(filters);
  const r = await fetch(url, { headers: { Accept: "text/csv" } });
  if (!r.ok) throw new Error(await readErrorMessage(r));
  const blob = await r.blob();
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objUrl;
  a.download = `jobpulse_export_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(objUrl);
}

export const fetchStats = () => getJson<Stats>(`${API}/stats`);
export const fetchCompanies = () => getJson<Company[]>(`${API}/companies`);
export const fetchRuns = (limit = 5) => getJson<ScrapeRun[]>(`${API}/scrape-runs?limit=${limit}`);
export const fetchCompanyHealth = () => getJson<CompanyHealth[]>(`${API}/stats/companies`);

export async function triggerScrape(companyId: number): Promise<void> {
  const r = await fetch(`${API}/companies/${companyId}/scrape`, {
    method: "POST",
    headers: mutateHeaders(),
  });
  if (!r.ok) throw new Error(await readErrorMessage(r));
}

export async function triggerScrapeAll(opts: { noPlaywright?: boolean } = {}): Promise<void> {
  const qs = opts.noPlaywright ? "?no_playwright=true" : "";
  const r = await fetch(`${API}/scrape-runs${qs}`, {
    method: "POST",
    headers: mutateHeaders(),
  });
  if (!r.ok) throw new Error(await readErrorMessage(r));
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

export interface UpdateCompanyPayload {
  active?: boolean;
}

export async function updateCompany(
  companyId: number,
  payload: UpdateCompanyPayload
): Promise<Company> {
  const r = await fetch(`${API}/companies/${companyId}`, {
    method: "PATCH",
    headers: mutateHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
    }),
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await readErrorMessage(r));
  return (await r.json()) as Company;
}

export async function createCompany(payload: CreateCompanyPayload): Promise<Company> {
  const r = await fetch(`${API}/companies`, {
    method: "POST",
    headers: mutateHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
    }),
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(await readErrorMessage(r));
  return (await r.json()) as Company;
}

export async function bulkImportCompanies(file: File): Promise<BulkImportResult> {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch(`${API}/companies/bulk-import`, {
    method: "POST",
    headers: mutateHeaders(),
    body: form,
  });
  if (!r.ok) throw new Error(await readErrorMessage(r));
  return (await r.json()) as BulkImportResult;
}
