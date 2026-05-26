import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  bulkImportCompanies,
  createCompany,
  detectAts,
  type CreateCompanyPayload,
} from "../api";
import type { BulkImportResult, DetectAtsResult } from "../types";

interface Props {
  onClose: () => void;
}

type Tab = "single" | "bulk";

const REQUIRED_SELECTOR_KEYS = ["list_item", "title", "apply_url"] as const;

function deriveName(url: string): string {
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./, "");
    return host.split(".")[0].replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  } catch {
    return "";
  }
}

export function AddCompanyModal({ onClose }: Props) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("single");

  // ---- single-add state ---------------------------------------------------
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [detection, setDetection] = useState<DetectAtsResult | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [selectorsText, setSelectorsText] = useState("");
  const [selectorsError, setSelectorsError] = useState<string | null>(null);

  // Debounced live detection. Auto-fills name from the host until the user
  // edits it manually.
  const [userTouchedName, setUserTouchedName] = useState(false);
  useEffect(() => {
    const trimmed = url.trim();
    if (!trimmed || !/^https?:\/\//i.test(trimmed)) {
      setDetection(null);
      return;
    }
    if (!userTouchedName) setName(deriveName(trimmed));
    setDetecting(true);
    const t = setTimeout(() => {
      detectAts(trimmed)
        .then((r) => setDetection(r))
        .catch(() => setDetection(null))
        .finally(() => setDetecting(false));
    }, 300);
    return () => clearTimeout(t);
  }, [url, userTouchedName]);

  const needsSelectors = detection !== null && !detection.recognized;

  const create = useMutation({
    mutationFn: (payload: CreateCompanyPayload) => createCompany(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["stats"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
      onClose();
    },
  });

  // ---- bulk-import state --------------------------------------------------
  const [file, setFile] = useState<File | null>(null);
  const bulk = useMutation({
    mutationFn: (f: File) => bulkImportCompanies(f),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["stats"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSelectorsError(null);
    const payload: CreateCompanyPayload = {
      name: name.trim(),
      careers_url: url.trim(),
    };
    if (needsSelectors) {
      const text = selectorsText.trim();
      if (!text) {
        setSelectorsError("This URL was not recognised; please provide selectors JSON.");
        return;
      }
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(text);
      } catch {
        setSelectorsError("Selectors must be valid JSON.");
        return;
      }
      const missing = REQUIRED_SELECTOR_KEYS.filter((k) => !(k in parsed));
      if (missing.length) {
        setSelectorsError(`Missing required keys: ${missing.join(", ")}`);
        return;
      }
      payload.ats_type = "custom";
      payload.custom_selectors = parsed;
    }
    create.mutate(payload);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-slate-900/40" onClick={onClose} />
      <div className="relative bg-white rounded-lg shadow-xl w-full max-w-xl mx-4 overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h2 className="text-lg font-semibold">Add company</h2>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-900 text-2xl leading-none px-2"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="border-b border-slate-200 px-5 flex gap-4 text-sm">
          {(["single", "bulk"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`py-2 -mb-px border-b-2 ${
                tab === t ? "border-slate-900 text-slate-900" : "border-transparent text-slate-500"
              }`}
            >
              {t === "single" ? "Single URL" : "Bulk CSV"}
            </button>
          ))}
        </div>

        {tab === "single" && (
          <form onSubmit={handleSubmit} className="px-5 py-4 space-y-3 text-sm">
            <label className="block">
              <span className="text-xs text-slate-600">Careers URL</span>
              <input
                type="url"
                required
                autoFocus
                placeholder="https://boards.greenhouse.io/anthropic"
                className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
            </label>

            <label className="block">
              <span className="text-xs text-slate-600">Display name</span>
              <input
                required
                className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5"
                value={name}
                onChange={(e) => {
                  setUserTouchedName(true);
                  setName(e.target.value);
                }}
              />
            </label>

            <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
              {detecting && <span className="text-slate-500">Detecting…</span>}
              {!detecting && detection?.recognized && (
                <span className="text-emerald-700">
                  Detected: <strong>{detection.ats_type}</strong>
                  {detection.ats_identifier ? ` · ${detection.ats_identifier}` : ""}
                </span>
              )}
              {!detecting && detection && !detection.recognized && (
                <span className="text-amber-700">
                  ATS not recognised — provide custom selectors below or save as <code>custom</code>.
                </span>
              )}
              {!detecting && !detection && (
                <span className="text-slate-400">Enter a URL to detect the ATS.</span>
              )}
            </div>

            {needsSelectors && (
              <label className="block">
                <span className="text-xs text-slate-600">
                  Custom selectors (JSON; required keys:{" "}
                  <code>list_item, title, apply_url</code>)
                </span>
                <textarea
                  rows={6}
                  className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5 font-mono text-xs"
                  placeholder={`{\n  "list_item": ".job-row",\n  "title": "h3",\n  "apply_url": "a@href",\n  "location": ".location"\n}`}
                  value={selectorsText}
                  onChange={(e) => setSelectorsText(e.target.value)}
                />
              </label>
            )}

            {selectorsError && (
              <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2">
                {selectorsError}
              </div>
            )}
            {create.isError && (
              <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2">
                {(create.error as Error).message}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="text-sm border border-slate-300 rounded px-3 py-1.5 hover:bg-slate-100"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={create.isPending}
                className="text-sm bg-slate-900 text-white rounded px-3 py-1.5 hover:bg-slate-700 disabled:opacity-50"
              >
                {create.isPending ? "Adding…" : "Add company"}
              </button>
            </div>
          </form>
        )}

        {tab === "bulk" && (
          <div className="px-5 py-4 space-y-3 text-sm">
            <p className="text-xs text-slate-600">
              CSV columns: <code>name, careers_url</code> (required) plus optional{" "}
              <code>ats_type</code>, <code>ats_identifier</code>. Unknown URLs fall back to{" "}
              <code>custom</code>. Idempotent on <code>name</code>.
            </p>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block text-sm"
            />
            {bulk.isError && (
              <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2">
                {(bulk.error as Error).message}
              </div>
            )}
            {bulk.data && <BulkResultBlock result={bulk.data} />}
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="text-sm border border-slate-300 rounded px-3 py-1.5 hover:bg-slate-100"
              >
                Close
              </button>
              <button
                type="button"
                disabled={!file || bulk.isPending}
                onClick={() => file && bulk.mutate(file)}
                className="text-sm bg-slate-900 text-white rounded px-3 py-1.5 hover:bg-slate-700 disabled:opacity-50"
              >
                {bulk.isPending ? "Uploading…" : "Import"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function BulkResultBlock({ result }: { result: BulkImportResult }) {
  return (
    <div className="text-xs border border-slate-200 rounded p-2 bg-slate-50">
      <div>
        <strong>{result.inserted}</strong> inserted · <strong>{result.updated}</strong> updated ·{" "}
        <strong>{result.skipped}</strong> skipped
      </div>
      {result.errors.length > 0 && (
        <ul className="mt-1 list-disc list-inside text-red-700 max-h-32 overflow-y-auto">
          {result.errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
