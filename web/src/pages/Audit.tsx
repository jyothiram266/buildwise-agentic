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
    <div className="space-y-4">
      <div className="sheet p-4">
        <SheetHeading eyebrow="Replay" title="Reconstruct a case from its trace" />
        <div className="mt-3 flex flex-wrap gap-2">
          <input
            className="field max-w-sm font-mono text-sm"
            placeholder="CASE-..."
            value={caseId}
            onChange={(event) => setCaseId(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && void load(caseId)}
          />
          <button className="btn-primary" onClick={() => void load(caseId)} disabled={busy}>
            {busy ? "Loading" : "Replay case"}
          </button>
        </div>
        <p className="mt-3 max-w-2xl text-xs leading-relaxed text-steel-dark">
          This reads only the case row, the append-only trace, the escalation and the review record —
          the same tables an auditor would be handed. Anything the trace cannot explain shows up as a
          gap here rather than being filled in from somewhere else.
        </p>
        {error && <p className="mt-3 text-sm text-signal-red">{error}</p>}
      </div>

      {busy && <Spinner label="reading trace" />}

      {!data && !busy && !error && (
        <Empty
          title="No case loaded"
          hint="Send a message in the conversation view, copy the case id from the reply, and paste it here."
        />
      )}

      {data && (
        <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
          <section className="sheet p-4">
            <SheetHeading
              eyebrow={`Case ${data.case_id}`}
              title="Decision path"
              right={
                <span
                  className={`font-mono text-micro uppercase tracking-wider ${
                    data.reproducible ? "text-signal-green" : "text-signal-amber"
                  }`}
                >
                  {data.reproducible ? "reproducible" : "gaps in trace"}
                </span>
              }
            />
            <div className="mt-4">
              <TraceSpine steps={data.steps} />
            </div>
          </section>

          <aside className="space-y-4">
            <div className="sheet p-4">
              <SheetHeading eyebrow="Outcome" title="What was sent" />
              <div className="mt-3 space-y-2">
                <TierBadge tier={caseRecord.risk_tier ?? null} />
                <p className="font-mono text-micro uppercase tracking-wider text-steel">
                  {caseRecord.response_mode ?? "no response recorded"}
                </p>
                <p className="whitespace-pre-wrap border-l-2 border-paper-deep pl-3 text-xs leading-relaxed text-ink-soft">
                  {caseRecord.response_text ?? "—"}
                </p>
              </div>
            </div>

            <div className="sheet p-4">
              <SheetHeading eyebrow="Versions in play" title="What produced this answer" />
              <dl className="mt-3 space-y-3 font-mono text-micro">
                <VersionRow label="prompts" values={data.versions.prompts} />
                <VersionRow label="policies" values={data.versions.policies} />
                <VersionRow label="models" values={data.versions.models} />
                <VersionRow label="sources" values={data.sources_used} />
              </dl>
            </div>

            {data.escalation && (
              <div className="border border-signal-red/40 bg-signal-red/5 p-4">
                <div className="label-micro text-signal-red">Escalation</div>
                <p className="mt-2 font-mono text-micro text-ink-soft">
                  {data.escalation.type} → {data.escalation.owner_team} · due{" "}
                  {data.escalation.sla_due}
                </p>
                <pre className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-steel-dark">
                  {data.escalation.brief ?? ""}
                </pre>
              </div>
            )}

            {data.human_review && (
              <div className="sheet p-4">
                <SheetHeading eyebrow="Human decision" title="Who acted, and how" />
                <dl className="mt-3 space-y-1.5 font-mono text-micro text-steel-dark">
                  <div className="flex justify-between gap-3">
                    <dt className="text-steel">action</dt>
                    <dd className="text-ink-soft">{data.human_review.action ?? "pending"}</dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-steel">actor</dt>
                    <dd className="text-ink-soft">{data.human_review.acted_by ?? "—"}</dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-steel">edited</dt>
                    <dd className="text-ink-soft">{data.human_review.was_edited ? "yes" : "no"}</dd>
                  </div>
                  {data.human_review.rejection_reason && (
                    <div className="flex justify-between gap-3">
                      <dt className="text-steel">reason</dt>
                      <dd className="text-signal-amber">{data.human_review.rejection_reason}</dd>
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
      <dt className="uppercase tracking-widest text-steel">{label}</dt>
      <dd className="mt-1 flex flex-wrap gap-1">
        {values.length === 0 ? (
          <span className="text-steel-light">none recorded</span>
        ) : (
          values.map((value) => (
            <span key={value} className="border border-paper-edge bg-paper px-1.5 py-0.5 text-steel-dark">
              {value}
            </span>
          ))
        )}
      </dd>
    </div>
  );
}
