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
          ? `Rejected and recorded as ${reason.replace(/_/g, " ")}. The case has been returned to the owning team.`
          : `Decision Approved & Sent. Single-use approval token (${result.approval_token?.slice(0, 12)}…) issued.`,
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
    <div className="grid gap-6 lg:grid-cols-[360px_1fr] font-sans">
      <section className="sheet flex max-h-[80vh] flex-col rounded-xl bg-white shadow-sheet overflow-hidden border border-slate-200/80">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4 bg-slate-50/50">
          <div>
            <div className="label-micro font-semibold text-slate-500">Human Governance</div>
            <p className="text-sm font-bold text-ink font-display">{items.length} Pending Review{items.length === 1 ? "" : "s"}</p>
          </div>
          <button className="btn-ghost px-3 py-1.5 text-xs font-semibold" onClick={() => void load()} disabled={loading}>
            Refresh
          </button>
        </div>
        <div className="flex-1 divide-y divide-slate-100 overflow-y-auto">
          {loading && (
            <div className="p-5">
              <Spinner label="Fetching approval queue..." />
            </div>
          )}
          {!loading && items.length === 0 && (
            <div className="p-5">
              <Empty
                title="Approval Queue Clear"
                hint="Drafts arrive here when risk tiering is Tier 2, when safety gates block auto-delivery, or on pipeline exceptions."
              />
            </div>
          )}
          {items.map((item) => (
            <button
              key={item.review_id}
              onClick={() => setSelected(item)}
              className={`block w-full px-5 py-4 text-left transition-all ${
                selected?.review_id === item.review_id
                  ? "bg-brand-50/40 border-l-4 border-l-brand-600"
                  : "bg-white hover:bg-slate-50/70"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <TierBadge tier={item.risk_tier} />
                {item.sla?.breached ? (
                  <span className="rounded bg-rose-100 px-2 py-0.5 font-mono text-micro font-bold uppercase text-rose-800 border border-rose-200">
                    SLA Breached
                  </span>
                ) : (
                  <span className="font-mono text-micro font-medium text-slate-500">
                    {item.sla ? `${Math.max(0, Math.round(item.sla.remaining_minutes / 60))}h remaining` : "No SLA"}
                  </span>
                )}
              </div>
              <p className="mt-2 line-clamp-2 text-xs font-medium leading-relaxed text-slate-800 font-sans">
                {item.original_request}
              </p>
              <div className="mt-2 flex items-center justify-between">
                <span className="font-mono text-micro text-slate-400">#{item.case_id}</span>
                <ConfidenceBadge value={item.confidence} />
              </div>
            </button>
          ))}
        </div>
      </section>

      <section className="space-y-5">
        {notice && (
          <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-xs font-semibold text-emerald-800 shadow-2xs">
            <svg className="h-5 w-5 text-emerald-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            <span>{notice}</span>
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs font-semibold text-rose-800 shadow-2xs">
            <div className="font-mono uppercase tracking-wider font-bold mb-1">Review Error</div>
            {error}
          </div>
        )}

        {!selected && !notice && (
          <Empty title="Select a Draft to Review" hint="Pick a pending item from the left queue to inspect the proposed response, citations, and risk reasoning." />
        )}

        {selected && (
          <>
            <div className="sheet p-5 bg-white shadow-sheet">
              <SheetHeading
                eyebrow={`Case ID: ${selected.case_id}`}
                title="Customer / Staff Request"
                right={<StatusPill status={selected.status} />}
              />
              <p className="mt-3.5 whitespace-pre-wrap text-sm leading-relaxed text-slate-800 font-sans bg-slate-50/70 p-4 rounded-lg border border-slate-100">
                {selected.original_request}
              </p>
              <div className="mt-3.5 flex flex-wrap items-center gap-3">
                <TierBadge tier={selected.risk_tier} />
                <ConfidenceBadge value={selected.confidence} />
                <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-micro font-bold uppercase text-slate-600 border border-slate-200">
                  Audience: {selected.audience}
                </span>
              </div>
            </div>

            <div className="sheet p-5 bg-white shadow-sheet">
              <SheetHeading eyebrow="Safety & Pipeline Reasoning" title="Why Human Approval is Required" />
              <div className="mt-3.5 rounded-lg bg-slate-50 p-3.5 border border-slate-200/70">
                <pre className="whitespace-pre-wrap font-sans text-xs leading-relaxed text-slate-700">
                  {selected.reasoning_summary}
                </pre>
              </div>
              {selected.citations.length > 0 && (
                <div className="mt-4">
                  <div className="label-micro mb-2 text-slate-500 font-semibold">Supporting Document Citations</div>
                  <div className="flex flex-wrap gap-1.5">
                    {selected.citations.map((citation) => (
                      <CitationChip key={`${citation.source_id}-${citation.section}`} citation={citation} />
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="sheet p-5 bg-white shadow-sheet">
              <SheetHeading
                eyebrow="Response Authorization"
                title="Proposed Response Draft"
                right={
                  <span className="font-mono text-micro text-slate-400">
                    {editing.length} characters
                  </span>
                }
              />
              <textarea
                className="field mt-3.5 min-h-[160px] font-sans text-sm leading-relaxed border-slate-200 focus:border-brand-500"
                value={editing}
                onChange={(event) => setEditing(event.target.value)}
                disabled={!canApprove}
              />

              {!canApprove ? (
                <div className="mt-4 rounded-lg bg-amber-50 p-3.5 border border-amber-200 text-xs text-amber-900 leading-relaxed font-sans">
                  <span className="font-bold">Role Limitation:</span> Your current identity ({actor.role}) can inspect this queue but lacks approval authority. Action privileges are reserved for Managers, Legal/Finance, and Site Engineers.
                </div>
              ) : (
                <div className="mt-4 flex flex-wrap items-center gap-3">
                  <button
                    className="btn-accent px-5 py-2 text-xs font-semibold shadow-xs"
                    disabled={busy}
                    onClick={() => void act(editing === selected.proposed_response ? "approve" : "edit_and_send")}
                  >
                    {editing === selected.proposed_response ? "Approve & Dispatch Response" : "Send Custom Edited Reply"}
                  </button>
                  <span className="h-6 w-px bg-slate-200 hidden sm:block" />
                  <div className="flex items-center gap-2">
                    <select
                      className="field w-auto font-sans text-xs border-slate-200 bg-white"
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                    >
                      {REJECTION_REASONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                    <button className="btn-danger px-4 py-2 text-xs font-semibold" disabled={busy} onClick={() => void act("reject")}>
                      Reject Draft
                    </button>
                  </div>
                </div>
              )}
              <div className="mt-3.5 text-xs leading-relaxed text-slate-500 font-mono">
                Security Guarantee: Approving issues a single-use authorization token evaluated inside SQL connector predicates prior to dispatch.
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
