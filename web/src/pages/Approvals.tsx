// The approval queue. This is where tier 2 stops being autonomous.
//
// Four actions, and the rejection reason is a fixed list rather than free text:
// the reason distribution is what tells the team which agent to fix, and prose
// cannot be counted.

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Actor, ReviewItem } from "../api/types";
import { CitationChip, ConfidenceBadge, Empty, SheetHeading, Spinner, StatusPill } from "../components/Bits";
import { TierBadge } from "../components/RiskLadder";

const REJECTION_REASONS = [
  { value: "factually_wrong", label: "Factually wrong" },
  { value: "missing_context", label: "Missing context" },
  { value: "wrong_tone", label: "Wrong tone" },
  { value: "policy_breach", label: "Policy breach" },
  { value: "over_promised", label: "Over-promised" },
  { value: "wrong_audience", label: "Wrong audience" },
  { value: "needs_specialist", label: "Needs a specialist" },
  { value: "duplicate", label: "Duplicate" },
];

export default function Approvals({ actor }: { actor: Actor }) {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [selected, setSelected] = useState<ReviewItem | null>(null);
  const [editing, setEditing] = useState("");
  const [reason, setReason] = useState(REJECTION_REASONS[0].value);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.review(actor.actor_id);
      setItems(result.items);
      setSelected((current) =>
        current ? result.items.find((i) => i.review_id === current.review_id) ?? null : result.items[0] ?? null,
      );
      setError(null);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, [actor.actor_id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setEditing(selected?.proposed_response ?? "");
  }, [selected?.review_id, selected?.proposed_response]);

  async function act(action: "approve" | "edit_and_send" | "reject") {
    if (!selected) return;
    setBusy(true);
    setNotice(null);
    try {
      const result = await api.act(actor.actor_id, selected.review_id, {
        action,
        edited_text: action === "edit_and_send" ? editing : undefined,
        rejection_reason: action === "reject" ? reason : undefined,
      });
      setNotice(
        action === "reject"
          ? `Rejected and recorded as ${reason.replace(/_/g, " ")}. The case is back with the team.`
          : `Sent. Approval token issued (${result.approval_token?.slice(0, 12)}…) and the case is closed to the actor.`,
      );
      setSelected(null);
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  const canApprove = ["manager", "legal_finance", "site_engineer"].includes(actor.role);

  return (
    <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
      <section className="sheet flex max-h-[78vh] flex-col">
        <div className="flex items-center justify-between border-b border-paper-edge px-4 py-3">
          <div>
            <div className="label-micro">Waiting on a person</div>
            <p className="text-sm font-medium text-ink">{items.length} in the queue</p>
          </div>
          <button className="btn-ghost" onClick={() => void load()} disabled={loading}>
            Refresh
          </button>
        </div>
        <div className="flex-1 divide-y divide-paper-edge overflow-y-auto">
          {loading && (
            <div className="p-4">
              <Spinner label="loading queue" />
            </div>
          )}
          {!loading && items.length === 0 && (
            <div className="p-4">
              <Empty
                title="Queue is clear"
                hint="Drafts arrive here when a case is tier 2, when the disclosure gate blocks an automatic send, or when the pipeline fails."
              />
            </div>
          )}
          {items.map((item) => (
            <button
              key={item.review_id}
              onClick={() => setSelected(item)}
              className={`block w-full px-4 py-3 text-left transition-colors hover:bg-paper ${
                selected?.review_id === item.review_id ? "bg-paper" : "bg-white"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <TierBadge tier={item.risk_tier} />
                {item.sla?.breached ? (
                  <span className="font-mono text-micro uppercase text-signal-red">SLA breached</span>
                ) : (
                  <span className="font-mono text-micro text-steel">
                    {item.sla ? `${Math.max(0, Math.round(item.sla.remaining_minutes / 60))}h left` : "—"}
                  </span>
                )}
              </div>
              <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-ink-soft">
                {item.original_request}
              </p>
              <div className="mt-1.5 flex items-center gap-2">
                <span className="font-mono text-micro text-steel-light">{item.case_id}</span>
                <ConfidenceBadge value={item.confidence} />
              </div>
            </button>
          ))}
        </div>
      </section>

      <section className="space-y-4">
        {notice && (
          <div className="border border-signal-green/40 bg-signal-green/5 p-3 text-sm text-signal-green">
            {notice}
          </div>
        )}
        {error && (
          <div className="border border-signal-red/40 bg-signal-red/5 p-3 text-sm text-signal-red">{error}</div>
        )}

        {!selected && !notice && (
          <Empty title="Nothing selected" hint="Pick an item from the queue to review the draft and the reasoning behind it." />
        )}

        {selected && (
          <>
            <div className="sheet p-4">
              <SheetHeading
                eyebrow={`Case ${selected.case_id}`}
                title="What was asked"
                right={<StatusPill status={selected.status} />}
              />
              <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-ink">
                {selected.original_request}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <TierBadge tier={selected.risk_tier} />
                <ConfidenceBadge value={selected.confidence} />
                <span className="font-mono text-micro uppercase tracking-wider text-steel">
                  audience {selected.audience}
                </span>
              </div>
            </div>

            <div className="sheet p-4">
              <SheetHeading eyebrow="Why it is here" title="Reasoning and route" />
              <pre className="mt-3 whitespace-pre-wrap font-mono text-xs leading-relaxed text-steel-dark">
                {selected.reasoning_summary}
              </pre>
              {selected.citations.length > 0 && (
                <div className="mt-3">
                  <div className="label-micro mb-1.5">Sources behind the draft</div>
                  <div className="flex flex-wrap gap-1.5">
                    {selected.citations.map((citation) => (
                      <CitationChip key={`${citation.source_id}-${citation.section}`} citation={citation} />
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="sheet p-4">
              <SheetHeading
                eyebrow="Proposed reply"
                title="Edit before sending, or send as drafted"
                right={
                  <span className="font-mono text-micro text-steel">
                    {editing.length} characters
                  </span>
                }
              />
              <textarea
                className="field mt-3 min-h-[180px] font-sans text-sm leading-relaxed"
                value={editing}
                onChange={(event) => setEditing(event.target.value)}
                disabled={!canApprove}
              />

              {!canApprove ? (
                <p className="mt-3 text-xs text-steel-dark">
                  Your role can read this queue but not act on it. Approving is limited to managers,
                  legal and finance, and site engineers.
                </p>
              ) : (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <button
                    className="btn-primary"
                    disabled={busy}
                    onClick={() => void act(editing === selected.proposed_response ? "approve" : "edit_and_send")}
                  >
                    {editing === selected.proposed_response ? "Approve and send" : "Send edited reply"}
                  </button>
                  <span className="mx-1 h-6 w-px bg-paper-edge" />
                  <select
                    className="field w-auto font-mono text-xs"
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                  >
                    {REJECTION_REASONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <button className="btn-danger" disabled={busy} onClick={() => void act("reject")}>
                    Reject with reason
                  </button>
                </div>
              )}
              <p className="mt-3 text-xs leading-relaxed text-steel-dark">
                Approving mints a single-use token. The connector checks that token itself before any
                write, so approval cannot be asserted by the code that wants to perform the action.
              </p>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
