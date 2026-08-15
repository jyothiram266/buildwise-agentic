// Audit viewer. Paste a case id, get the decision path back: which prompt version,
// which policy version, which model, which sources, and what a human did.
//
// The "reproducible" flag is the honest headline. If a step has no prompt version
// recorded, the case cannot be reproduced exactly, and the viewer says so rather
// than implying an audit trail that does not hold up.

import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { Actor, CaseRecord, Replay } from "../api/types";
import { Empty, SheetHeading, Spinner } from "../components/Bits";
import { TierBadge } from "../components/RiskLadder";
import { TraceSpine } from "../components/TraceSpine";

export default function Audit({ actor, initialCaseId }: { actor: Actor; initialCaseId?: string }) {
  const [caseId, setCaseId] = useState(initialCaseId ?? "");
  const [data, setData] = useState<Replay | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(id: string) {
    if (!id.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setData(await api.replay(actor.actor_id, id.trim()));
    } catch (exc) {
      setData(null);
      setError(exc instanceof ApiError ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  const caseRecord: CaseRecord = data?.case ?? {};

  return (
    <div className="space-y-6 font-sans">
      <div className="sheet p-5 bg-white shadow-sheet">
        <SheetHeading eyebrow="Trace & Governance Audit" title="Deterministic Case Execution Replay" />
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <div className="relative flex-1 max-w-md">
            <input
              className="field w-full font-mono text-sm pl-9 border-slate-200 focus:border-brand-500"
              placeholder="Enter Case ID (e.g. CASE-2026...)"
              value={caseId}
              onChange={(event) => setCaseId(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && void load(caseId)}
            />
            <svg className="h-4 w-4 text-slate-400 absolute left-3 top-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
          <button className="btn-accent px-5 py-2 text-xs font-semibold" onClick={() => void load(caseId)} disabled={busy}>
            {busy ? "Replaying Trace..." : "Replay Case Decision"}
          </button>
        </div>
        <p className="mt-3 max-w-3xl text-xs leading-relaxed text-slate-500 font-sans">
          Reconstructs execution directly from append-only audit traces, policy registry versions, model parameters, and human review records. Unverified assertions are flagged as trace gaps.
        </p>
        {error && (
          <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3.5 text-xs font-semibold text-rose-800">
            {error}
          </div>
        )}
      </div>

      {busy && <Spinner label="Loading immutable trace logs..." />}

      {!data && !busy && !error && (
        <Empty
          title="No Case Trace Loaded"
          hint="Send a message in the conversation view, copy the Case ID from the bottom response meta, and paste it above to audit the pipeline execution."
        />
      )}

      {data && (
        <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
          <section className="sheet p-5 bg-white shadow-sheet">
            <SheetHeading
              eyebrow={`Audit Trail — Case #${data.case_id}`}
              title="Execution Spine & Agent Sequence"
              right={
                <span
                  className={`rounded-md px-2.5 py-1 font-mono text-micro font-bold uppercase tracking-wider ${
                    data.reproducible ? "bg-emerald-100 text-emerald-800 border border-emerald-200" : "bg-amber-100 text-amber-800 border border-amber-200"
                  }`}
                >
                  {data.reproducible ? "Deterministic Trace Verified" : "Gaps in Trace History"}
                </span>
              }
            />
            <div className="mt-5">
              <TraceSpine steps={data.steps} />
            </div>
          </section>

          <aside className="space-y-6">
            <div className="sheet p-5 bg-white shadow-sheet">
              <SheetHeading eyebrow="Final Output" title="Delivered Response" />
              <div className="mt-3.5 space-y-3">
                <div className="flex items-center gap-2">
                  <TierBadge tier={caseRecord.risk_tier ?? null} />
                  <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-micro font-bold uppercase text-slate-700">
                    {caseRecord.response_mode ?? "No Response"}
                  </span>
                </div>
                <div className="rounded-lg bg-slate-50 p-3.5 border border-slate-200/70 text-xs leading-relaxed text-slate-800 whitespace-pre-wrap font-sans">
                  {caseRecord.response_text ?? "—"}
                </div>
              </div>
            </div>

            <div className="sheet p-5 bg-white shadow-sheet">
              <SheetHeading eyebrow="Provenance" title="Active Artifact Versions" />
              <dl className="mt-3.5 space-y-3.5 font-mono text-micro">
                <VersionRow label="Prompt Templates" values={data.versions.prompts} />
                <VersionRow label="Policy Modules" values={data.versions.policies} />
                <VersionRow label="LLM Engines" values={data.versions.models} />
                <VersionRow label="Retrieved Corpus Files" values={data.sources_used} />
              </dl>
            </div>

            {data.escalation && (
              <div className="rounded-xl border border-rose-200 bg-rose-50/80 p-4 shadow-2xs">
                <div className="label-micro font-bold text-rose-900">Escalation Ticket</div>
                <p className="mt-2 font-mono text-micro text-rose-950 font-semibold">
                  {data.escalation.type} → {data.escalation.owner_team} · Due {data.escalation.sla_due}
                </p>
                <pre className="mt-2 max-h-56 overflow-y-auto whitespace-pre-wrap rounded-md bg-white p-3 font-mono text-micro text-slate-700 border border-rose-200/60">
                  {data.escalation.brief ?? ""}
                </pre>
              </div>
            )}

            {data.human_review && (
              <div className="sheet p-5 bg-white shadow-sheet">
                <SheetHeading eyebrow="Governance Action" title="Human Staff Review" />
                <dl className="mt-3.5 space-y-2.5 font-mono text-micro">
                  <div className="flex items-center justify-between gap-3 border-b border-slate-100 pb-1.5">
                    <dt className="text-slate-500 uppercase font-medium">Action</dt>
                    <dd className="font-bold text-slate-800 uppercase">{data.human_review.action ?? "Pending"}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-3 border-b border-slate-100 pb-1.5">
                    <dt className="text-slate-500 uppercase font-medium">Reviewer</dt>
                    <dd className="font-semibold text-slate-800">{data.human_review.acted_by ?? "—"}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-3 border-b border-slate-100 pb-1.5">
                    <dt className="text-slate-500 uppercase font-medium">Draft Edited</dt>
                    <dd className="font-bold text-slate-800">{data.human_review.was_edited ? "Yes" : "No"}</dd>
                  </div>
                  {data.human_review.rejection_reason && (
                    <div className="flex items-center justify-between gap-3 border-b border-slate-100 pb-1.5">
                      <dt className="text-slate-500 uppercase font-medium">Rejection Category</dt>
                      <dd className="font-bold text-amber-700">{data.human_review.rejection_reason}</dd>
                    </div>
                  )}
                </dl>
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

function VersionRow({ label, values }: { label: string; values: string[] }) {
  return (
    <div>
      <dt className="uppercase tracking-wider text-slate-400 font-medium">{label}</dt>
      <dd className="mt-1.5 flex flex-wrap gap-1.5">
        {values.length === 0 ? (
          <span className="text-slate-400 font-sans text-xs italic">None Recorded</span>
        ) : (
          values.map((value) => (
            <span key={value} className="rounded border border-slate-200/80 bg-slate-50 px-2 py-0.5 font-mono text-micro text-slate-700 font-medium">
              {value}
            </span>
          ))
        )}
      </dd>
    </div>
  );
}
