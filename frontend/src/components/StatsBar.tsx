import type { ScrapeRun, Stats } from "../types";

interface Props {
  stats: Stats | undefined;
  runs: ScrapeRun[] | undefined;
}

function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "—";
  const mins = Math.floor(ms / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function Tile({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-3 shadow-sm">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-2xl font-semibold text-slate-900 leading-tight">{value}</div>
      {sub && <div className="text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

export function StatsBar({ stats, runs }: Props) {
  const lastRun = runs?.[0] ?? stats?.last_run ?? null;
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
      <Tile label="Active jobs" value={stats?.jobs_active ?? "—"} sub={`${stats?.jobs_total ?? 0} total`} />
      <Tile label="Last 15 days" value={stats?.jobs_last_15d ?? "—"} sub="newly posted" />
      <Tile
        label="Companies"
        value={stats?.companies_active ?? "—"}
        sub={`${stats?.companies_total ?? 0} total`}
      />
      <Tile
        label="Last scrape"
        value={fmtAgo(lastRun?.finished_at ?? lastRun?.started_at ?? null)}
        sub={lastRun ? `${lastRun.status} · ${lastRun.jobs_new_total} new` : ""}
      />
      <Tile
        label="Run jobs found"
        value={lastRun?.jobs_found_total ?? "—"}
        sub={lastRun ? `${lastRun.companies_scraped} companies` : ""}
      />
    </div>
  );
}
