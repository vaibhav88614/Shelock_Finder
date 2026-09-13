import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteResume,
  fetchResume,
  rescoreResume,
  uploadResumeFile,
  uploadResumeText,
} from "../api";
import type { ResumeInfo } from "../types";

interface Props {
  onClose: () => void;
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

/**
 * Modal panel for uploading / viewing / clearing the active resume.
 *
 * Backend rescoring runs as a FastAPI BackgroundTask, so we poll the
 * /resume endpoint every 2s while `scored_at` lags behind `uploaded_at`.
 * A visible progress line ("scoring 12,345 jobs…") keeps the user oriented
 * while it happens.
 */
export function ResumePanel({ onClose }: Props) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"text" | "file">("text");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const resume = useQuery({
    queryKey: ["resume"],
    queryFn: fetchResume,
    // Poll while a rescore is in-flight (uploaded_at is set, scored_at
    // still null). One 2s tick is enough for the full-corpus run to land
    // on realistic DBs (<1s on 20k jobs).
    refetchInterval: (q) => {
      const r = q.state.data as ResumeInfo | null | undefined;
      if (r && !r.scored_at) return 2000;
      return false;
    },
  });

  const upload = useMutation({
    mutationFn: async () => {
      setUploadError(null);
      if (tab === "text") {
        if (text.trim().length < 20) {
          throw new Error("Please paste at least 20 characters of resume text.");
        }
        return uploadResumeText(text);
      }
      if (!file) throw new Error("Pick a file first.");
      return uploadResumeFile(file);
    },
    onSuccess: () => {
      setText("");
      setFile(null);
      qc.invalidateQueries({ queryKey: ["resume"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e: Error) => setUploadError(e.message),
  });

  const clear = useMutation({
    mutationFn: deleteResume,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["resume"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  const rescore = useMutation({
    mutationFn: rescoreResume,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["resume"] }),
  });

  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onEsc);
    return () => document.removeEventListener("keydown", onEsc);
  }, [onClose]);

  const r = resume.data;
  const scoringInFlight = Boolean(r && !r.scored_at);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="resume-panel-title"
    >
      <div className="absolute inset-0 bg-slate-900/40" onClick={onClose} aria-hidden="true" />
      <div
        ref={dialogRef}
        className="relative bg-white dark:bg-slate-900 dark:text-slate-100 rounded-lg shadow-xl w-full max-w-2xl mx-4 overflow-hidden"
      >
        <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 px-5 py-3">
          <h2 id="resume-panel-title" className="text-lg font-semibold">
            Resume &amp; match scoring
          </h2>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-900 dark:hover:text-white text-2xl leading-none px-2"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="px-5 py-4 space-y-4 text-sm">
          {r ? (
            <div className="rounded border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/60 p-3 text-xs">
              <div className="flex flex-wrap justify-between gap-2">
                <div>
                  <strong>Active resume:</strong> {r.name}
                  {r.filename ? (
                    <span className="text-slate-500 dark:text-slate-400">
                      {" "}
                      · {r.filename}
                    </span>
                  ) : null}
                </div>
                <div className="text-slate-500 dark:text-slate-400">
                  uploaded {fmtAgo(r.uploaded_at)}
                </div>
              </div>
              <div className="mt-1 text-slate-600 dark:text-slate-300">
                {r.text_length.toLocaleString()} chars · {r.bag_size} unique terms ·{" "}
                {r.matches_total.toLocaleString()} scored (
                {r.matches_nonzero.toLocaleString()} nonzero)
              </div>
              <div className="mt-1">
                {scoringInFlight ? (
                  <span className="text-amber-700 dark:text-amber-400">
                    Scoring jobs… this usually completes in a second or two.
                  </span>
                ) : (
                  <span className="text-emerald-700 dark:text-emerald-400">
                    Scoring complete {fmtAgo(r.scored_at)}.
                  </span>
                )}
              </div>
              <div className="mt-2 flex gap-2 flex-wrap">
                <button
                  type="button"
                  onClick={() => rescore.mutate()}
                  disabled={rescore.isPending || scoringInFlight}
                  className="text-xs border border-slate-300 dark:border-slate-700 rounded px-2 py-1 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50"
                >
                  {rescore.isPending ? "Queued…" : "Rescore all jobs"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (window.confirm("Remove the active resume and its match scores?")) {
                      clear.mutate();
                    }
                  }}
                  disabled={clear.isPending}
                  className="text-xs border border-red-300 dark:border-red-800 text-red-700 dark:text-red-300 rounded px-2 py-1 hover:bg-red-50 dark:hover:bg-red-950/30 disabled:opacity-50"
                >
                  Clear
                </button>
              </div>
              {clear.isError && (
                <div className="mt-2 text-red-700 dark:text-red-400">
                  Clear failed: {(clear.error as Error).message}
                </div>
              )}
            </div>
          ) : (
            <div className="rounded border border-dashed border-slate-300 dark:border-slate-700 p-3 text-xs text-slate-500 dark:text-slate-400">
              No resume uploaded yet. Paste text or upload a PDF / TXT file below.
              Once processed, sort the jobs list by <strong>Match score</strong> to
              see the strongest overlaps first.
            </div>
          )}

          <div>
            <h3 className="text-xs font-semibold text-slate-700 dark:text-slate-200 uppercase mb-2">
              {r ? "Replace resume" : "Add resume"}
            </h3>
            <div className="border-b border-slate-200 dark:border-slate-800 flex gap-4 text-sm mb-3">
              {(["text", "file"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`py-2 -mb-px border-b-2 ${
                    tab === t
                      ? "border-slate-900 dark:border-slate-100"
                      : "border-transparent text-slate-500 dark:text-slate-400"
                  }`}
                >
                  {t === "text" ? "Paste text" : "Upload file"}
                </button>
              ))}
            </div>
            {tab === "text" ? (
              <label className="block">
                <span className="text-xs text-slate-600 dark:text-slate-300">
                  Paste your resume (plain text, ≥ 20 chars)
                </span>
                <textarea
                  rows={10}
                  className="mt-1 w-full border border-slate-300 dark:border-slate-700 dark:bg-slate-900 rounded px-2 py-1.5 font-mono text-xs"
                  placeholder="Skilled software engineer with 5 years of Python, FastAPI, PostgreSQL…"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
              </label>
            ) : (
              <label className="block">
                <span className="text-xs text-slate-600 dark:text-slate-300">
                  Upload a resume file (PDF, TXT, or MD)
                </span>
                <input
                  type="file"
                  accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="mt-1 block text-xs"
                />
              </label>
            )}
            {uploadError && (
              <div className="mt-2 text-xs text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 rounded p-2">
                {uploadError}
              </div>
            )}
            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="text-sm border border-slate-300 dark:border-slate-700 rounded px-3 py-1.5 hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                Close
              </button>
              <button
                type="button"
                onClick={() => upload.mutate()}
                disabled={upload.isPending}
                className="text-sm bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900 rounded px-3 py-1.5 hover:bg-slate-700 dark:hover:bg-white disabled:opacity-50"
              >
                {upload.isPending ? "Uploading…" : r ? "Replace" : "Upload"}
              </button>
            </div>
          </div>

          <p className="text-[11px] text-slate-500 dark:text-slate-400 border-t border-slate-200 dark:border-slate-800 pt-3">
            <strong>How this works.</strong> Your resume is tokenised into a
            bag-of-words locally (no LLM, no network). We compute a BM25 score
            against every active job's title + description + department + location.
            Sort the jobs list by <em>Match score</em> to see the strongest
            overlaps; the drawer highlights the terms that contributed.
          </p>
        </div>
      </div>
    </div>
  );
}
