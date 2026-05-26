import type { Job } from "../types";

interface Props {
  job: Job | null;
  onClose: () => void;
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

export function JobDrawer({ job, onClose }: Props) {
  if (!job) return null;
  return (
    <div className="fixed inset-0 z-40 flex" role="dialog" aria-modal="true">
      <div
        className="absolute inset-0 bg-slate-900/30"
        onClick={onClose}
        aria-label="Close"
      />
      <div className="ml-auto relative w-full max-w-xl h-full bg-white shadow-xl overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-slate-200 px-5 py-3 flex items-start justify-between">
          <div className="min-w-0">
            <div className="text-xs text-slate-500">
              {job.company_name ?? `#${job.company_id}`}
            </div>
            <h2 className="text-lg font-semibold leading-tight truncate">{job.title}</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-500 hover:text-slate-900 text-2xl leading-none px-2"
            aria-label="Close drawer"
          >
            ×
          </button>
        </div>

        <div className="px-5 py-4 space-y-4 text-sm">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
            <dt className="text-slate-500">Location</dt>
            <dd>{job.location ?? "—"}</dd>
            <dt className="text-slate-500">Remote</dt>
            <dd>{job.remote_type ?? "—"}</dd>
            <dt className="text-slate-500">Department</dt>
            <dd>{job.department ?? "—"}</dd>
            <dt className="text-slate-500">Employment</dt>
            <dd>{job.employment_type ?? "—"}</dd>
            <dt className="text-slate-500">Experience</dt>
            <dd>
              {job.experience_min ?? "—"}–{job.experience_max ?? "—"} yrs
            </dd>
            <dt className="text-slate-500">Posted</dt>
            <dd>{fmtDateTime(job.posted_date)}</dd>
            <dt className="text-slate-500">First seen</dt>
            <dd>{fmtDateTime(job.first_seen_at)}</dd>
            <dt className="text-slate-500">Last seen</dt>
            <dd>{fmtDateTime(job.last_seen_at)}</dd>
          </dl>

          {job.keywords_matched.length > 0 && (
            <div>
              <div className="text-slate-500 text-xs uppercase mb-1">Matched</div>
              <div className="flex flex-wrap gap-1">
                {job.keywords_matched.map((k) => (
                  <span
                    key={k}
                    className="inline-block bg-amber-100 text-amber-800 text-xs rounded px-1.5 py-0.5"
                  >
                    {k}
                  </span>
                ))}
              </div>
            </div>
          )}

          <a
            href={job.apply_url}
            target="_blank"
            rel="noreferrer"
            className="inline-block bg-slate-900 text-white text-sm rounded px-3 py-1.5 hover:bg-slate-700"
          >
            Open posting ↗
          </a>

          {job.description && (
            <section>
              <h3 className="text-slate-500 text-xs uppercase mb-1">Description</h3>
              <div className="prose prose-sm max-w-none whitespace-pre-wrap text-slate-800">
                {job.description}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
