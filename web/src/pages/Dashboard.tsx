// Operations dashboard. Every panel here answers a question someone asks in a
// review, and the pairs are deliberate: automation next to refusal, groundedness
// next to override rate. A single number in isolation is easy to game.

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { Actor, Dashboard as DashboardData } from "../api/types";
import { Empty, SheetHeading, Spinner } from "../components/Bits";
import { RISK_RUNGS } from "../components/RiskLadder";

export default function Dashboard({ actor }: { actor: Actor }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [windowDays, setWindowDays] = useState(30);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.dashboard(actor.actor_id, windowDays));
      setError(null);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, [actor.actor_id, windowDays]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !data) return <Spinner label="loading metrics" />;
  if (error) {
    return (
      <div className="border border-signal-red/40 bg-signal-red/5 p-4 text-sm text-signal-red">{error}</div>
    );
  }
  if (!data) return <Empty title="No metrics" hint="Run a few cases first, then come back." />;

  const { volume, latency, cost, confidence, human_review: review, maintenance } = data;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="label-micro">Operations</div>
          <h1 className="text-xl font-semibold tracking-tight text-ink">
            {volume.cases} case{volume.cases === 1 ? "" : "s"} in the last {data.window_days} days
          </h1>
        </div>
        <div className="flex gap-2">
          {[7, 30, 90].map((days) => (
            <button
              key={days}
              className={windowDays === days ? "btn-primary" : "btn-ghost"}
              onClick={() => setWindowDays(days)}
            >
              {days}d
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric
          label="Answered without a person"
          value={pct(volume.automation_rate)}
          detail={`${volume.answered} of ${volume.cases}`}
        />
        <Metric
          label="Refused honestly"
          value={pct(volume.refusal_rate)}
          detail="shown next to automation on purpose — refusing everything would look like perfect grounding"
          tone={volume.refusal_rate > 0.25 ? "warn" : "neutral"}
        />
        <Metric
          label="Escalated to a human"
          value={pct(volume.escalation_rate)}
          detail={`${volume.escalated} tier-3 acknowledgements`}
        />
        <Metric
          label="Override rate"
          value={pct(review.override_rate)}
          detail={`target under ${pct(review.target)} · ${review.decided} decisions`}
          tone={review.override_rate > review.target ? "warn" : "good"}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel eyebrow="Autonomy" title="Where cases land on the risk ladder">
          {data.risk_tiers.length === 0 ? (
            <Empty title="No tiered cases yet" hint="Send a message from the conversation view to populate this." />
          ) : (
            <div className="space-y-2.5">
              {RISK_RUNGS.map((rung) => {
                const row = data.risk_tiers.find((t) => t.tier === rung.tier);
                const count = row?.count ?? 0;
                const share = volume.cases ? count / volume.cases : 0;
                return (
                  <Bar
                    key={rung.tier}
                    label={`T${rung.tier} ${rung.label}`}
                    hint={rung.detail}
                    value={count}
                    share={share}
                    tone={["good", "neutral", "warn", "bad"][rung.tier] as BarTone}
                  />
                );
              })}
            </div>
          )}
        </Panel>

        <Panel eyebrow="Language understanding" title="Intent mix and confidence">
          {data.intents.length === 0 ? (
            <Empty title="No classified cases" hint="Intent distribution appears once cases have run." />
          ) : (
            <div className="space-y-2.5">
              {data.intents.map((row) => (
                <Bar
                  key={row.intent}
                  label={row.intent.toLowerCase().replace(/_/g, " ")}
                  hint={`average confidence ${pct(row.avg_confidence)}`}
                  value={row.count}
                  share={volume.cases ? row.count / volume.cases : 0}
                  tone={row.avg_confidence >= 0.7 ? "neutral" : "warn"}
                />
              ))}
            </div>
          )}
        </Panel>

        <Panel eyebrow="Escalations" title="Who owns what, and is it inside SLA">
          {data.escalations.length === 0 ? (
            <Empty title="Nothing escalated" hint="Tier-3 cases and their owning teams appear here with SLA state." />
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="label-micro">
                <tr>
                  <th className="pb-2">Type</th>
                  <th className="pb-2">Owner</th>
                  <th className="pb-2 text-right">Open</th>
                  <th className="pb-2 text-right">Breached</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-paper-edge font-mono">
                {data.escalations.map((row) => (
                  <tr key={`${row.type}-${row.owner_team}`}>
                    <td className="py-1.5 text-ink">{row.type.replace(/_/g, " ")}</td>
                    <td className="py-1.5 text-steel-dark">{row.owner_team.replace(/_/g, " ")}</td>
                    <td className="py-1.5 text-right text-ink">{row.open}</td>
                    <td
                      className={`py-1.5 text-right ${row.sla_breached ? "text-signal-red" : "text-steel"}`}
                    >
                      {row.sla_breached}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <Panel eyebrow="Human review" title="Why people changed a draft">
          <div className="grid grid-cols-3 gap-3 border-b border-paper-edge pb-3">
            <Mini label="Approved as drafted" value={review.approved} />
            <Mini label="Edited then sent" value={review.edited} />
            <Mini label="Rejected" value={review.rejected} />
          </div>
          {review.reasons.length === 0 ? (
            <p className="mt-3 text-xs text-steel-dark">
              No rejections recorded. The reason breakdown is the actionable half of override rate —
              it points at which agent needs work.
            </p>
          ) : (
            <div className="mt-3 space-y-2">
              {review.reasons.map((row) => (
                <Bar
                  key={row.reason}
                  label={row.reason.replace(/_/g, " ")}
                  value={row.count}
                  share={review.decided ? row.count / review.decided : 0}
                  tone="warn"
                />
              ))}
            </div>
          )}
          {review.pending > 0 && (
            <p className="mt-3 font-mono text-micro uppercase tracking-wider text-signal-amber">
              {review.pending} still waiting on a person
            </p>
          )}
        </Panel>

        <Panel eyebrow="Cost and latency" title="What a case costs to answer">
          <div className="grid grid-cols-3 gap-3 border-b border-paper-edge pb-3">
            <Mini label="Per case" value={`$${cost.per_case_usd.toFixed(5)}`} />
            <Mini label="P95 latency" value={`${(latency.p95_ms / 1000).toFixed(1)}s`} tone={latency.within_target ? "good" : "bad"} />
            <Mini label="Tokens" value={cost.tokens.toLocaleString()} />
          </div>
          <p className="mt-2 font-mono text-micro text-steel">
            target P95 under {latency.target_p95_ms / 1000}s for a multi-agent case · median time to
            first response {formatDuration(latency.median_response_seconds)} (includes waiting for a
            human on tier 2)
          </p>
          {cost.by_intent.length > 0 && (
            <div className="mt-3 space-y-2">
              {cost.by_intent.slice(0, 6).map((row) => (
                <Bar
                  key={row.intent}
                  label={row.intent.toLowerCase().replace(/_/g, " ")}
                  hint={`$${row.avg_cost_usd.toFixed(5)} average · ${row.cases} cases`}
                  value={Number(row.cost_usd.toFixed(4))}
                  share={cost.total_usd ? row.cost_usd / cost.total_usd : 0}
                  tone="neutral"
                />
              ))}
            </div>
          )}
        </Panel>

        <Panel eyebrow="Maintenance" title="Tickets and service levels">
          <div className="grid grid-cols-2 gap-3">
            <Mini label="Tickets on record" value={maintenance.tickets} />
            <Mini
              label="Past SLA"
              value={maintenance.sla_breached}
              tone={maintenance.sla_breached > 0 ? "bad" : "good"}
            />
            <Mini label="P1 raised" value={maintenance.p1} />
            <Mini label="Warranty flagged" value={maintenance.warranty_flagged} />
          </div>
          <div className="mt-4 border-t border-paper-edge pt-3">
            <div className="label-micro mb-2">Confidence distribution</div>
            <div className="space-y-2">
              {confidence.bands.map((band) => (
                <Bar
                  key={band.band}
                  label={band.band}
                  value={band.count}
                  share={volume.cases ? band.count / volume.cases : 0}
                  tone={band.band === "<0.5" || band.band === "0.5-0.7" ? "warn" : "neutral"}
                />
              ))}
            </div>
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel eyebrow="Schedule" title="Milestones past their planned date">
          {data.delayed_milestones.length === 0 ? (
            <Empty title="Nothing slipping" hint="Every milestone is on or ahead of its planned date." />
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="label-micro">
                <tr>
                  <th className="pb-2">Tower</th>
                  <th className="pb-2">Milestone</th>
                  <th className="pb-2">Planned</th>
                  <th className="pb-2 text-right">Slip</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-paper-edge font-mono">
                {data.delayed_milestones.map((row) => (
                  <tr key={`${row.tower}-${row.milestone}`}>
                    <td className="py-1.5 text-ink">{row.tower}</td>
                    <td className="py-1.5 text-steel-dark">{row.milestone}</td>
                    <td className="py-1.5 text-steel">{row.planned_date}</td>
                    <td
                      className={`py-1.5 text-right ${
                        row.slip_days >= 14 ? "text-signal-red" : "text-signal-amber"
                      }`}
                    >
                      {row.slip_days}d
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {data.escalation_ageing.length > 0 && (
            <div className="mt-4 border-t border-paper-edge pt-3">
              <div className="label-micro mb-2">Escalation queue ageing</div>
              <div className="grid grid-cols-4 gap-2">
                {data.escalation_ageing.map((bucket) => (
                  <div key={bucket.bucket}>
                    <div className="label-micro">{bucket.bucket}</div>
                    <p
                      className={`mt-1 font-mono text-lg font-semibold ${
                        bucket.sla_breached > 0 ? "text-signal-red" : "text-ink"
                      }`}
                    >
                      {bucket.count}
                    </p>
                    {bucket.sla_breached > 0 && (
                      <p className="font-mono text-micro text-signal-red">
                        {bucket.sla_breached} past SLA
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </Panel>

        <Panel eyebrow="Sales" title="Leads needing follow-up today">
          {data.leads_due_today.length === 0 ? (
            <Empty title="Nothing due" hint="No open lead has a follow-up due today or overdue." />
          ) : (
            <ul className="divide-y divide-paper-edge">
              {data.leads_due_today.map((lead) => (
                <li key={lead.lead_id} className="flex items-center justify-between gap-3 py-2">
                  <div className="min-w-0">
                    <p className="truncate text-xs text-ink">{lead.name}</p>
                    <p className="font-mono text-micro text-steel">
                      {lead.next_action ?? "no action set"}
                      {lead.next_action_due ? ` · due ${lead.next_action_due}` : ""}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="font-mono text-sm text-ink">{lead.score}</p>
                    <p className="font-mono text-micro text-steel">
                      {lead.days_since_contact}d since contact
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      {data.kb_gaps.length > 0 && (
        <Panel eyebrow="Content backlog" title="Questions the knowledge base could not answer">
          <ul className="divide-y divide-paper-edge">
            {data.kb_gaps.map((gap) => (
              <li key={`${gap.query}-${gap.role}`} className="flex items-center justify-between gap-4 py-2">
                <span className="text-xs text-ink-soft">{gap.query}</span>
                <span className="shrink-0 font-mono text-micro text-steel">
                  {gap.role} · {gap.hits}×
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-steel-dark">
            Each row is a query that retrieved nothing. That is a content problem rather than a model
            problem, which is why it is logged separately and shown to the people who write the corpus.
          </p>
        </Panel>
      )}
    </div>
  );
}

type BarTone = "good" | "neutral" | "warn" | "bad";

const TONE_BAR: Record<BarTone, string> = {
  good: "bg-signal-green",
  neutral: "bg-signal-blue",
  warn: "bg-signal-amber",
  bad: "bg-signal-red",
};

const TONE_TEXT: Record<BarTone, string> = {
  good: "text-signal-green",
  neutral: "text-ink",
  warn: "text-signal-amber",
  bad: "text-signal-red",
};

function pct(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatDuration(seconds: number) {
  if (!seconds) return "n/a";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function Metric({
  label,
  value,
  detail,
  tone = "neutral",
}: {
  label: string;
  value: string;
  detail: string;
  tone?: BarTone;
}) {
  return (
    <div className="sheet ticked p-4">
      <div className="label-micro">{label}</div>
      <p className={`mt-2 font-mono text-2xl font-semibold ${TONE_TEXT[tone]}`}>{value}</p>
      <p className="mt-1 text-xs leading-relaxed text-steel-dark">{detail}</p>
    </div>
  );
}

function Panel({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="sheet p-4">
      <SheetHeading eyebrow={eyebrow} title={title} />
      <div className="mt-3">{children}</div>
    </section>
  );
}

function Mini({ label, value, tone = "neutral" }: { label: string; value: number | string; tone?: BarTone }) {
  return (
    <div>
      <div className="label-micro">{label}</div>
      <p className={`mt-1 font-mono text-lg font-semibold ${TONE_TEXT[tone]}`}>{value}</p>
    </div>
  );
}

function Bar({
  label,
  hint,
  value,
  share,
  tone = "neutral",
}: {
  label: string;
  hint?: string;
  value: number;
  share: number;
  tone?: BarTone;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-xs text-ink">{label}</span>
        <span className="font-mono text-micro text-steel-dark">{value}</span>
      </div>
      <div className="mt-1 h-1.5 w-full bg-paper-deep">
        <div
          className={`h-full ${TONE_BAR[tone]}`}
          style={{ width: `${Math.max(share * 100, value > 0 ? 2 : 0)}%` }}
        />
      </div>
      {hint && <p className="mt-1 font-mono text-micro text-steel">{hint}</p>}
    </div>
  );
}
