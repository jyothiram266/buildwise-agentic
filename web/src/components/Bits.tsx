// Small shared pieces: confidence, citations, status, section headings.

import type { ReactNode } from "react";

import type { Citation } from "../api/types";

export function ConfidenceBadge({ value }: { value: number | null }) {
  if (value === null || Number.isNaN(value)) return null;
  const pct = Math.round(value * 100);
  // Below 0.70 the pipeline routes to a human, so the threshold is where the
  // colour changes — the badge and the policy agree.
  const tone =
    value >= 0.85
      ? "text-signal-green border-signal-green/40"
      : value >= 0.7
        ? "text-signal-blue border-signal-blue/40"
        : "text-signal-amber border-signal-amber/50";
  return (
    <span
      title={`Lowest confidence in the pipeline. Below 70% a human reviews before sending.`}
      className={`inline-flex items-center gap-1 border px-1.5 py-0.5 font-mono text-micro ${tone}`}
    >
      <span className="opacity-60">conf</span>
      {pct}%
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
      className={`inline-flex max-w-full items-center gap-1.5 border px-2 py-1 font-mono text-micro ${
        citation.is_stale
          ? "border-signal-amber/50 bg-signal-amber/5 text-signal-amber"
          : "border-paper-edge bg-paper text-steel-dark"
      }`}
    >
      <span className="truncate">{citation.source_id}</span>
      {citation.is_stale && <span aria-hidden>·stale</span>}
    </span>
  );
}

export function StatusPill({ status }: { status: string }) {
  const tone: Record<string, string> = {
    answered: "border-signal-green/40 text-signal-green",
    awaiting_approval: "border-signal-amber/50 text-signal-amber",
    escalated: "border-signal-red/40 text-signal-red",
    failed: "border-signal-red/40 text-signal-red",
    rejected: "border-steel-light text-steel-dark",
    open: "border-steel-light text-steel-dark",
  };
  return (
    <span
      className={`inline-block border px-1.5 py-0.5 font-mono text-micro uppercase tracking-wider ${
        tone[status] ?? "border-steel-light text-steel-dark"
      }`}
    >
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
    <div className="flex items-end justify-between gap-4 border-b border-paper-edge pb-3">
      <div>
        <div className="label-micro">{eyebrow}</div>
        <h2 className="mt-1 text-lg font-semibold tracking-tight text-ink">{title}</h2>
      </div>
      {right}
    </div>
  );
}

export function Empty({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="border border-dashed border-paper-edge bg-white/60 p-8 text-center">
      <p className="font-mono text-xs uppercase tracking-widest text-steel">{title}</p>
      <p className="mx-auto mt-2 max-w-sm text-sm text-steel-dark">{hint}</p>
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-steel">
      <span className="h-2 w-2 animate-pulse bg-signal-blue" />
      {label}
    </div>
  );
}
