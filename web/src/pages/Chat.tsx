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
    <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
      <section className="sheet ticked flex min-h-[70vh] flex-col">
        <div className="flex items-center justify-between border-b border-paper-edge px-4 py-3">
          <div>
            <div className="label-micro">Conversation</div>
            <p className="text-sm font-medium text-ink">{actor.display_name}</p>
          </div>
          {busy && <Spinner label="running agents" />}
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto bg-blueprint bg-blueprint p-4">
          {turns.length === 0 && (
            <div className="space-y-3">
              <Empty
                title="Nothing asked yet"
                hint="Send a message as this role, or pick one of the prompts below to see how the same system answers different people."
              />
              <div className="flex flex-wrap gap-2">
                {(SUGGESTIONS[actor.role] ?? []).map((suggestion) => (
                  <button
                    key={suggestion}
                    className="btn-ghost max-w-full text-left normal-case tracking-normal"
                    onClick={() => send(suggestion)}
                  >
                    <span className="truncate">{suggestion}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          {turns.map((turn, index) => (
            <MessageBubble key={index} turn={turn} />
          ))}
          {error && (
            <div className="border border-signal-red/40 bg-signal-red/5 p-3 text-sm text-signal-red">
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
          placeholder="Type a message. Cmd/Ctrl + Enter sends."
        />
      </section>

      <aside className="space-y-4">
        <div className="sheet p-4">
          <SheetHeading
            eyebrow="Access scope"
            title="What this actor can see"
            right={<span className="font-mono text-micro uppercase text-steel">{actor.role}</span>}
          />
          <dl className="mt-3 space-y-2 font-mono text-micro text-steel-dark">
            <ScopeRow label="bookings" values={actor.booking_ids} />
            <ScopeRow label="units" values={actor.unit_ids} />
            <ScopeRow label="projects" values={actor.project_ids} />
            <ScopeRow label="work packages" values={actor.work_package_ids} />
          </dl>
          <p className="mt-3 text-xs leading-relaxed text-steel-dark">
            Retrieval and every system call filter on this scope in SQL. An out-of-scope record
            returns nothing rather than an error, so the answer cannot reveal that it exists.
          </p>
        </div>

        {internalFindings.length > 0 && (
          <div className="sheet p-4">
            <SheetHeading
              eyebrow="Agent findings"
              title="Reasoning behind the reply"
              right={
                <button className="btn-ghost" onClick={() => setShowFindings((v) => !v)}>
                  {showFindings ? "Hide" : "Show"}
                </button>
              }
            />
            {showFindings && (
              <ul className="mt-3 space-y-3">
                {internalFindings.map((finding) => (
                  <li key={finding.agent} className="border-l-2 border-paper-deep pl-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs font-medium uppercase tracking-wider text-ink">
                        {finding.agent}
                      </span>
                      <span
                        className={`font-mono text-micro uppercase ${
                          finding.status === "ok" ? "text-signal-green" : "text-signal-amber"
                        }`}
                      >
                        {finding.status}
                      </span>
                      <ConfidenceBadge value={finding.confidence} />
                      {finding.internal_only && (
                        <span className="border border-signal-red/40 px-1 font-mono text-micro uppercase text-signal-red">
                          internal only
                        </span>
                      )}
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-steel-dark">
                      {finding.summary}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {latest && latest.degraded_reasons.length > 0 && (
          <div className="border border-signal-amber/50 bg-signal-amber/5 p-4">
            <div className="label-micro text-signal-amber">Degraded</div>
            <ul className="mt-2 space-y-1 text-xs text-steel-dark">
              {latest.degraded_reasons.map((reason) => (
                <li key={reason}>— {reason}</li>
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
    <div className="flex justify-between gap-3">
      <dt className="uppercase tracking-wider text-steel">{label}</dt>
      <dd className="text-right text-ink-soft">
        {values.length ? values.join(", ") : label === "projects" ? "all (role-wide)" : "none"}
      </dd>
    </div>
  );
}
