// Chat surface shared by the customer and staff views. The difference between the
// two is what the API returns, not what this component renders — so a bug here
// cannot expose internal findings to a customer.

import type { CaseResponse } from "../api/types";
import { CitationChip, ConfidenceBadge } from "./Bits";
import { TierBadge } from "./RiskLadder";

export type Turn = { role: "actor" | "system"; text: string; meta?: CaseResponse };

const MODE_NOTE: Record<string, string> = {
  auto_send: "Sent automatically",
  draft_for_approval: "Held as a draft — a person approves this before it is sent",
  acknowledgement_only: "Acknowledgement only — the owning team takes it from here",
  refuse: "No grounded answer available",
};

export function MessageBubble({ turn }: { turn: Turn }) {
  if (turn.role === "actor") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] border border-ink bg-ink px-4 py-3 text-sm leading-relaxed text-paper">
          {turn.text}
        </div>
      </div>
    );
  }

  const meta = turn.meta;
  return (
    <div className="flex justify-start">
      <div className="ticked max-w-[85%] border border-paper-edge bg-white px-4 py-3 shadow-sheet">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">{turn.text}</p>

        {meta && (
          <div className="mt-3 space-y-2 border-t border-paper-edge pt-2.5">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <TierBadge tier={meta.risk_tier} />
              <ConfidenceBadge value={meta.confidence} />
              {meta.mode && (
                <span className="font-mono text-micro uppercase tracking-wider text-steel">
                  {MODE_NOTE[meta.mode] ?? meta.mode}
                </span>
              )}
            </div>

            {meta.citations.length > 0 && (
              <div>
                <div className="label-micro mb-1">Sources</div>
                <div className="flex flex-wrap gap-1.5">
                  {meta.citations.map((citation) => (
                    <CitationChip key={`${citation.source_id}-${citation.section}`} citation={citation} />
                  ))}
                </div>
              </div>
            )}

            {meta.masked_entities.length > 0 && (
              <p className="font-mono text-micro text-steel">
                masked before processing: {meta.masked_entities.join(", ").toLowerCase()}
              </p>
            )}

            <div className="flex flex-wrap gap-x-4 font-mono text-micro text-steel">
              <span>{meta.latency_ms} ms</span>
              <span>{meta.cost_tokens} tok</span>
              <span>${meta.cost_usd.toFixed(4)}</span>
              <span className="text-steel-light">{meta.case_id}</span>
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
    <div className="flex items-end gap-2 border-t border-paper-edge bg-white p-3">
      <textarea
        className="field min-h-[44px] resize-y"
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
      <button className="btn-primary h-[44px] shrink-0" onClick={onSend} disabled={busy || !value.trim()}>
        {busy ? "Working" : "Send"}
      </button>
    </div>
  );
}
