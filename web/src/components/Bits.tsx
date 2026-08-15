// Small shared pieces: confidence, citations, status, section headings.

import type { ReactNode } from "react";
import type { Citation } from "../api/types";

export function ConfidenceBadge({ value }: { value: number | null }) {
  if (value === null || Number.isNaN(value)) return null;
  const pct = Math.round(value * 100);
  const tone =
    value >= 0.85
      ? "bg-emerald-50 text-emerald-700 border-emerald-300/80 shadow-2xs"
      : value >= 0.7
        ? "bg-blue-50 text-blue-700 border-blue-300/80 shadow-2xs"
        : "bg-amber-50 text-amber-700 border-amber-300/80 shadow-2xs";

  const dot =
    value >= 0.85
      ? "bg-emerald-500"
      : value >= 0.7
        ? "bg-blue-500"
        : "bg-amber-500";

  return (
    <span
      title={`Lowest confidence in the pipeline: ${pct}%. Below 70% a human reviews before sending.`}
      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-micro font-medium ${tone}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      <span className="opacity-70">conf</span>
      <span>{pct}%</span>
    </span>
  );
}

export function CitationChip({ citation }: { citation: Citation }) {
  return (
    <span
      title={[
        citation.source_name,
        citation.section ?? "",
        citation.effective_date ? `effective ${citation.effective_date}` : "",
        citation.is_stale ? "past its review window" : "",
      ]
        .filter(Boolean)
        .join(" · ")}
      className={`inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-micro font-medium transition-colors hover:border-slate-400 ${
        citation.is_stale
          ? "border-amber-300 bg-amber-50 text-amber-800"
          : "border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100"
      }`}
    >
      <svg className="h-3 w-3 text-slate-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
      <span className="truncate">{citation.source_id}</span>
      {citation.is_stale && <span className="rounded bg-amber-200/80 px-1 py-0.2 text-[9px] font-semibold uppercase text-amber-900">stale</span>}
    </span>
  );
}

export function StatusPill({ status }: { status: string }) {
  const tone: Record<string, { bg: string; text: string; border: string; dot: string }> = {
    answered: { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200", dot: "bg-emerald-500" },
    awaiting_approval: { bg: "bg-amber-50", text: "text-amber-700", border: "border-amber-200", dot: "bg-amber-500" },
    escalated: { bg: "bg-rose-50", text: "text-rose-700", border: "border-rose-200", dot: "bg-rose-500" },
    failed: { bg: "bg-rose-50", text: "text-rose-700", border: "border-rose-200", dot: "bg-rose-500" },
    rejected: { bg: "bg-slate-100", text: "text-slate-700", border: "border-slate-200", dot: "bg-slate-400" },
    open: { bg: "bg-slate-50", text: "text-slate-700", border: "border-slate-200", dot: "bg-slate-400" },
  };
  const style = tone[status] ?? { bg: "bg-slate-50", text: "text-slate-700", border: "border-slate-200", dot: "bg-slate-400" };

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-micro uppercase tracking-wider font-semibold ${style.bg} ${style.text} ${style.border}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function SheetHeading({
  eyebrow,
  title,
  right,
}: {
  eyebrow: string;
  title: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-slate-100 pb-3.5">
      <div>
        <div className="label-micro font-semibold">{eyebrow}</div>
        <h2 className="mt-0.5 text-base font-semibold tracking-tight text-ink font-display">{title}</h2>
      </div>
      {right}
    </div>
  );
}

export function Empty({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/50 p-8 text-center backdrop-blur-xs">
      <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-400 mb-3">
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
        </svg>
      </div>
      <p className="font-mono text-xs uppercase tracking-widest text-slate-500 font-medium">{title}</p>
      <p className="mx-auto mt-1.5 max-w-xs text-xs text-slate-500 leading-relaxed">{hint}</p>
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2.5 font-mono text-xs uppercase tracking-wider text-slate-600 font-medium">
      <span className="relative flex h-3 w-3">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-brand-500 opacity-75"></span>
        <span className="relative inline-flex rounded-full h-3 w-3 bg-brand-600"></span>
      </span>
      {label}
    </div>
  );
}
