// Chat surface shared by the customer and staff views. The difference between the
// two is what the API returns, not what this component renders — so a bug here
// cannot expose internal findings to a customer.

import type { CaseResponse } from "../api/types";
import { CitationChip, ConfidenceBadge } from "./Bits";
import { TierBadge } from "./RiskLadder";

export type Turn = { role: "actor" | "system"; text: string; meta?: CaseResponse };

const MODE_NOTE: Record<string, string> = {
  auto_send: "Auto-Delivered",
  draft_for_approval: "Held for Staff Approval (Tier 2)",
  acknowledgement_only: "Escalated to Human Owner (Tier 3)",
  refuse: "Refused (Insufficient Data Grounding)",
};

export function MessageBubble({ turn }: { turn: Turn }) {
  if (turn.role === "actor") {
    return (
      <div className="flex justify-end gap-3">
        <div className="max-w-[80%] rounded-2xl rounded-tr-xs bg-ink px-4 py-3 text-sm leading-relaxed text-white shadow-sm font-sans">
          {turn.text}
        </div>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-200 text-slate-700 font-mono text-xs font-semibold">
          You
        </div>
      </div>
    );
  }

  const meta = turn.meta;
  return (
    <div className="flex justify-start gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white font-mono text-xs font-bold shadow-xs">
        BW
      </div>
      <div className="sheet ticked max-w-[85%] rounded-2xl rounded-tl-xs p-4 shadow-sheet border-slate-200/80 bg-white">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800 font-sans">{turn.text}</p>

        {meta && (
          <div className="mt-3.5 space-y-2.5 border-t border-slate-100 pt-3">
            <div className="flex flex-wrap items-center gap-2">
              <TierBadge tier={meta.risk_tier} />
              <ConfidenceBadge value={meta.confidence} />
              {meta.mode && (
                <span className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-micro font-medium uppercase text-slate-600">
                  {MODE_NOTE[meta.mode] ?? meta.mode}
                </span>
              )}
            </div>

            {meta.citations.length > 0 && (
              <div className="pt-1">
                <div className="label-micro mb-1 text-slate-400 font-semibold">Grounding Citations</div>
                <div className="flex flex-wrap gap-1.5">
                  {meta.citations.map((citation) => (
                    <CitationChip key={`${citation.source_id}-${citation.section}`} citation={citation} />
                  ))}
                </div>
              </div>
            )}

            {meta.masked_entities.length > 0 && (
              <div className="flex items-center gap-1.5 font-mono text-micro text-amber-700 bg-amber-50 px-2 py-1 rounded border border-amber-200/60">
                <svg className="h-3.5 w-3.5 text-amber-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
                <span>PII Masked before LLM: {meta.masked_entities.join(", ").toLowerCase()}</span>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-x-4 border-t border-slate-100 pt-2 font-mono text-micro text-slate-500">
              <div className="flex items-center gap-3">
                <span className="flex items-center gap-1">
                  <svg className="h-3 w-3 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {meta.latency_ms} ms
                </span>
                <span>{meta.cost_tokens.toLocaleString()} tokens</span>
                <span className="font-medium text-slate-700">${meta.cost_usd.toFixed(4)}</span>
              </div>
              <span className="font-mono text-slate-400 hover:text-slate-600 cursor-pointer" title="Copy Case ID" onClick={() => navigator.clipboard.writeText(meta.case_id)}>
                #{meta.case_id}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function Composer({
  value,
  onChange,
  onSend,
  busy,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  busy: boolean;
  placeholder: string;
}) {
  return (
    <div className="flex items-end gap-2.5 border-t border-slate-200/80 bg-white/80 backdrop-blur-xs p-3.5 rounded-b-xl">
      <textarea
        className="field min-h-[48px] resize-none"
        rows={2}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            onSend();
          }
        }}
      />
      <button className="btn-accent h-[48px] shrink-0 px-5" onClick={onSend} disabled={busy || !value.trim()}>
        {busy ? (
          <span className="flex items-center gap-1.5">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
            Working
          </span>
        ) : (
          <span className="flex items-center gap-1.5">
            <span>Send</span>
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
          </span>
        )}
      </button>
    </div>
  );
}
