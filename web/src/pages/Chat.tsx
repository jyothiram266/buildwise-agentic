// Conversation view. Used by every role — external actors see the reply and its
// sources; internal actors additionally get the findings panel, because the API
// sends it to them.

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Actor, CaseResponse } from "../api/types";
import { Composer, MessageBubble, type Turn } from "../components/Chat";
import { ConfidenceBadge, Empty, SheetHeading, Spinner } from "../components/Bits";

const SUGGESTIONS: Record<string, string[]> = {
  public_lead: [
    "Do you have any 2BHK under 85 lakhs in Whitefield?",
    "What is the price for a 3BHK at Aurora Heights?",
    "Any 1BHK available at Aurora Heights?",
  ],
  customer: [
    "What documents are still pending for my registration?",
    "What is the construction status of my tower?",
    "Why has my possession date moved? I want a refund if this continues.",
  ],
  resident: [
    "There is water leaking from the bathroom ceiling and it is spreading.",
    "I can smell gas near the kitchen pipe.",
    "The lift has been out of service since yesterday.",
  ],
  broker: ["What inventory is available at Palm Meridian right now?"],
  contractor: [
    "Cement supply has stopped at Tower B, we have zero stock. When will you release my payment?",
  ],
  sales_staff: ["Who should I follow up with today?"],
  site_engineer: [
    "B blk slab 7 done 60%, curing on. steel short, vendor says 3 days. lift shaft measurement mismatch, 40mm off. told them to hold. possession may slip to Mar.",
  ],
  legal_finance: ["Show me the document position for booking BK-9901."],
  manager: ["What is the construction status and blocker position for Tower B?"],
};

export default function Chat({ actor }: { actor: Actor }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showFindings, setShowFindings] = useState(true);
  const bottom = useRef<HTMLDivElement>(null);

  // A role switch is a different person: clearing the transcript prevents reading
  // one actor's conversation in another actor's session.
  useEffect(() => {
    setTurns([]);
    setError(null);
  }, [actor.actor_id]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function send(text: string) {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    setDraft("");
    setTurns((prev) => [...prev, { role: "actor", text }]);
    try {
      const result: CaseResponse = await api.send(actor.actor_id, text);
      setTurns((prev) => [
        ...prev,
        { role: "system", text: result.text ?? "(no response text was produced)", meta: result },
      ]);
    } catch (exc) {
      const message = exc instanceof ApiError ? exc.message : String(exc);
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  const latest = [...turns].reverse().find((t) => t.meta)?.meta;
  const internalFindings = latest?.findings ?? [];

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
      <section className="sheet flex min-h-[75vh] flex-col rounded-xl overflow-hidden shadow-sheet bg-white">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5 bg-slate-50/50">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-200 text-slate-700 font-semibold text-xs">
              {actor.display_name.charAt(0)}
            </div>
            <div>
              <div className="label-micro font-semibold">Active Session</div>
              <p className="text-sm font-semibold text-ink font-display">{actor.display_name}</p>
            </div>
          </div>
          {busy ? (
            <Spinner label="Orchestrating agents..." />
          ) : (
            <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 font-mono text-micro font-medium text-emerald-700 border border-emerald-200">
              Ready
            </span>
          )}
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto bg-slate-50/40 p-5">
          {turns.length === 0 && (
            <div className="space-y-5 py-4">
              <Empty
                title="Conversation Ready"
                hint="Send a custom request or choose from suggested prompt scenarios mapped to this role."
              />
              <div className="rounded-xl border border-slate-200/80 bg-white p-4 shadow-2xs">
                <p className="label-micro mb-3 text-slate-500 font-semibold">Sample Scenarios for {actor.role.replace(/_/g, " ")}</p>
                <div className="flex flex-col gap-2">
                  {(SUGGESTIONS[actor.role] ?? []).map((suggestion) => (
                    <button
                      key={suggestion}
                      className="group flex items-center justify-between rounded-lg border border-slate-200/70 bg-slate-50/50 px-3.5 py-2.5 text-left text-xs text-slate-700 transition-all hover:border-brand-500 hover:bg-brand-50/40 hover:text-brand-700 font-sans"
                      onClick={() => send(suggestion)}
                    >
                      <span className="leading-relaxed">{suggestion}</span>
                      <svg className="h-4 w-4 text-slate-400 group-hover:text-brand-600 shrink-0 transition-transform group-hover:translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
          {turns.map((turn, index) => (
            <MessageBubble key={index} turn={turn} />
          ))}
          {error && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-xs font-medium text-rose-800 shadow-2xs">
              <div className="font-mono uppercase tracking-wider font-bold mb-1">Execution Error</div>
              {error}
            </div>
          )}
          <div ref={bottom} />
        </div>

        <Composer
          value={draft}
          onChange={setDraft}
          onSend={() => send(draft)}
          busy={busy}
          placeholder="Ask a question or report an issue. Press Cmd/Ctrl + Enter to send."
        />
      </section>

      <aside className="space-y-6">
        <div className="sheet p-5 bg-white">
          <SheetHeading
            eyebrow="Security & Security Scope"
            title="Authorized Data Scope"
            right={
              <span className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-micro font-bold uppercase text-slate-700 border border-slate-200">
                {actor.role}
              </span>
            }
          />
          <dl className="mt-4 space-y-2.5 font-mono text-micro">
            <ScopeRow label="Bookings" values={actor.booking_ids} />
            <ScopeRow label="Units" values={actor.unit_ids} />
            <ScopeRow label="Projects" values={actor.project_ids} />
            <ScopeRow label="Work Packages" values={actor.work_package_ids} />
          </dl>
          <div className="mt-4 rounded-lg bg-blue-50/60 p-3 border border-blue-100 text-xs leading-relaxed text-blue-900">
            <span className="font-semibold">Row-Level Security:</span> Queries are pre-filtered at SQL retrieval using this scope. Unreachable data returns no results.
          </div>
        </div>

        {internalFindings.length > 0 && (
          <div className="sheet p-5 bg-white">
            <SheetHeading
              eyebrow="Specialist Agent Insights"
              title="Pipeline Reasoning"
              right={
                <button className="btn-ghost px-2.5 py-1 text-[11px]" onClick={() => setShowFindings((v) => !v)}>
                  {showFindings ? "Collapse" : "Expand"}
                </button>
              }
            />
            {showFindings && (
              <ul className="mt-4 space-y-3.5">
                {internalFindings.map((finding) => (
                  <li key={finding.agent} className="rounded-lg border border-slate-200/80 bg-slate-50/50 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs font-bold uppercase tracking-wider text-ink">
                        {finding.agent}
                      </span>
                      <span
                        className={`rounded px-1.5 py-0.2 font-mono text-micro font-bold uppercase ${
                          finding.status === "ok" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"
                        }`}
                      >
                        {finding.status}
                      </span>
                      <ConfidenceBadge value={finding.confidence} />
                      {finding.internal_only && (
                        <span className="rounded bg-rose-100 px-1.5 py-0.2 font-mono text-micro font-bold uppercase text-rose-800 border border-rose-200">
                          Internal Only
                        </span>
                      )}
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-slate-700 font-sans">
                      {finding.summary}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {latest && latest.degraded_reasons.length > 0 && (
          <div className="rounded-xl border border-amber-300/80 bg-amber-50 p-4 shadow-2xs">
            <div className="label-micro font-bold text-amber-900">Degraded State Note</div>
            <ul className="mt-2 space-y-1 text-xs text-amber-800">
              {latest.degraded_reasons.map((reason) => (
                <li key={reason}>• {reason}</li>
              ))}
            </ul>
          </div>
        )}
      </aside>
    </div>
  );
}

function ScopeRow({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-slate-100 pb-1.5">
      <dt className="uppercase tracking-wider text-slate-500 font-medium">{label}</dt>
      <dd className="text-right font-semibold text-slate-800">
        {values.length ? values.join(", ") : label === "Projects" ? "All (Role Access)" : "None"}
      </dd>
    </div>
  );
}
