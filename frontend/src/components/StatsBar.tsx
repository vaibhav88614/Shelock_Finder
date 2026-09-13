import { memo } from "react";
import type { ScrapeRun, SparklinePoint, SparklinesOut, Stats } from "../types";
import { Sparkline } from "./Sparkline";

interface Props {
  stats: Stats | undefined;
  runs: ScrapeRun[] | undefined;
  sparklines: SparklinesOut | undefined;
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

function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}

interface TileProps {
  label: string;
  value: string | number;
  sub?: string;
  /** 0..1 — draws a horizontal progress bar under the sub-label when set. */
  progress?: number;
  progressLabel?: string;
  sparkline?: SparklinePoint[];
  sparklineLabel?: string;
  tooltip?: string;
}

function Tile({
  label,
  value,
  sub,
  progress,
  progressLabel,
  sparkline,
  sparklineLabel,
  tooltip,
}: TileProps) {
  return (
    <div
      className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg p-3 shadow-sm flex flex-col gap-1"
      title={tooltip}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
            {label}
          </div>
          <div className="text-2xl font-semibold text-slate-900 dark:text-slate-100 leading-tight truncate">
            {value}
          </div>
        </div>
        {sparkline && (
          <div
            className="shrink-0 self-center"
            title={sparklineLabel ?? "recent trend"}
            aria-label={sparklineLabel ?? "recent trend"}
          >
            <Sparkline points={sparkline} width={72} height={26} />
          </div>
        )}
      </div>
      {sub && (
        <div className="text-xs text-slate-500 dark:text-slate-400 truncate">
          {sub}
        </div>
      )}
      {progress !== undefined && (
        <div
          className="h-1 rounded bg-slate-100 dark:bg-slate-800 overflow-hidden"
          role="progressbar"
          aria-valuenow={Math.round(progress * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={progressLabel ?? label}
          title={progressLabel}
        >
          <div
            className="h-full bg-emerald-500 dark:bg-emerald-400 transition-[width]"
            style={{ width: `${Math.max(0, Math.min(1, progress)) * 100}%` }}
          />
        </div>
      )}
    </div>
  );
}

export const StatsBar = memo(function StatsBar({ stats, runs, sparklines }: Props) {
  const lastRun = runs?.[0] ?? stats?.last_run ?? null;
  const jobsRatio =
    stats && stats.jobs_total > 0 ? stats.jobs_active / stats.jobs_total : undefined;
  const companiesRatio =
    stats && stats.companies_total > 0
      ? stats.companies_active / stats.companies_total
      : undefined;

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
      <Tile
        label="Active jobs"
        value={fmtNum(stats?.jobs_active)}
        sub={`${fmtNum(stats?.jobs_total)} total`}
        progress={jobsRatio}
        progressLabel={
          jobsRatio !== undefined
            ? `${Math.round(jobsRatio * 100)}% of tracked jobs are currently active`
            : undefined
        }
        sparkline={sparklines?.active_per_day}
        sparklineLabel="Active postings per day (30d)"
        tooltip={
          "Rows in the jobs table with is_active=True (the source's careers page " +
          "still shows them). The sub-value is the total row count including " +
          "already-closed postings. The progress bar reflects active / total."
        }
      />
      <Tile
        label="Last 15 days"
        value={fmtNum(stats?.jobs_last_15d)}
        sub="newly posted"
        sparkline={sparklines?.new_jobs_per_day}
        sparklineLabel="New postings per day (30d)"
        tooltip={
          "Active jobs whose posted_date is within the last 15 days OR whose " +
          "posted_date is unknown (many custom-scraped rows lack one). Tuned " +
          "via JOBPULSE_POSTED_WITHIN_DAYS_MAX."
        }
      />
      <Tile
        label="Companies"
        value={fmtNum(stats?.companies_active)}
        sub={`${fmtNum(stats?.companies_total)} total`}
        progress={companiesRatio}
        progressLabel={
          companiesRatio !== undefined
            ? `${Math.round(companiesRatio * 100)}% of companies are scrape-enabled`
            : undefined
        }
        tooltip={
          "Companies with active=True (included in the next scrape run). Total " +
          "includes disabled rows and India custom companies still missing " +
          "selectors. Toggle scraping per row from the Admin tab."
        }
      />
      <Tile
        label="Last scrape"
        value={fmtAgo(lastRun?.finished_at ?? lastRun?.started_at ?? null)}
        sub={lastRun ? `${lastRun.status} · ${lastRun.jobs_new_total} new` : ""}
        sparkline={sparklines?.runs_jobs_new}
        sparklineLabel="Jobs added per run (last 25)"
        tooltip={
          "Time since the most recent scrape run finished. Status: ok = every " +
          "company succeeded, partial = at least one failed, failed = the whole " +
          "run bombed, running = in flight. The sparkline plots jobs_new_total " +
          "over the last 25 finished runs."
        }
      />
      <Tile
        label="Run jobs found"
        value={fmtNum(lastRun?.jobs_found_total)}
        sub={lastRun ? `${lastRun.companies_scraped} companies` : ""}
        sparkline={sparklines?.runs_jobs_found}
        sparklineLabel="Jobs found per run (last 25)"
        tooltip={
          "Every row emitted by every adapter during the last run before dedupe. " +
          "Includes existing jobs whose last_seen_at was refreshed as well as " +
          "truly new ones. The sparkline plots jobs_found_total across the last " +
          "25 finished runs."
        }
      />
    </div>
  );
});
