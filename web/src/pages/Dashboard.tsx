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

  if (loading && !data) return <Spinner label="Loading operational intelligence..." />;
  if (error) {
    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50 p-5 text-sm font-semibold text-rose-800 shadow-2xs">
        <div className="font-mono uppercase tracking-wider font-bold mb-1">Dashboard Metric Error</div>
        {error}
      </div>
    );
  }
  if (!data) return <Empty title="No Metrics Available" hint="Execute a few customer queries to populate real-time operational metrics." />;

  const { volume, latency, cost, confidence, human_review: review, maintenance } = data;

  return (
    <div className="space-y-6 font-sans">
      {/* Header bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200/70 pb-4">
        <div>
          <div className="label-micro font-semibold text-slate-500">Executive Overview</div>
          <h1 className="text-2xl font-bold tracking-tight text-ink font-display">
            {volume.cases} Case{volume.cases === 1 ? "" : "s"} Handled in {data.window_days} Days
          </h1>
        </div>
        <div className="flex items-center gap-1.5 rounded-lg bg-slate-100 p-1 border border-slate-200/80">
          {[7, 30, 90].map((days) => (
            <button
              key={days}
              className={`rounded-md px-3 py-1 font-mono text-xs uppercase font-semibold transition-all ${
                windowDays === days
                  ? "bg-white text-ink shadow-2xs"
                  : "text-slate-500 hover:text-ink"
              }`}
              onClick={() => setWindowDays(days)}
            >
              {days} Days
            </button>
          ))}
        </div>
      </div>

      {/* Top 4 KPI Metrics */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          label="Automated Resolution"
          value={pct(volume.automation_rate)}
          detail={`${volume.answered} of ${volume.cases} queries auto-resolved`}
          icon={
            <svg className="h-5 w-5 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
          tone="good"
        />
        <MetricCard
          label="Honest Refusal Rate"
          value={pct(volume.refusal_rate)}
          detail="Grounded safety gate prevents hallucinated prices or dates"
          icon={
            <svg className="h-5 w-5 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          }
          tone={volume.refusal_rate > 0.25 ? "warn" : "neutral"}
        />
        <MetricCard
          label="Human Escalation Rate"
          value={pct(volume.escalation_rate)}
          detail={`${volume.escalated} high-risk cases routed to team SLA queue`}
          icon={
            <svg className="h-5 w-5 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
            </svg>
          }
          tone="neutral"
        />
        <MetricCard
          label="Staff Override Rate"
          value={pct(review.override_rate)}
          detail={`Target < ${pct(review.target)} · ${review.decided} total decisions`}
          icon={
            <svg className="h-5 w-5 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
          }
          tone={review.override_rate > review.target ? "warn" : "good"}
        />
      </div>

      {/* Main Grid Section */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel eyebrow="Policy Autonomy" title="Risk Tier Distribution">
          {data.risk_tiers.length === 0 ? (
            <Empty title="No Tiered Cases Yet" hint="Submit queries to view automatic risk classification distribution." />
          ) : (
            <div className="space-y-3.5">
              {RISK_RUNGS.map((rung) => {
                const row = data.risk_tiers.find((t) => t.tier === rung.tier);
                const count = row?.count ?? 0;
                const share = volume.cases ? count / volume.cases : 0;
                const tones: BarTone[] = ["good", "neutral", "warn", "bad"];
                return (
                  <Bar
                    key={rung.tier}
                    label={`Tier ${rung.tier} — ${rung.label}`}
                    hint={rung.detail}
                    value={count}
                    share={share}
                    tone={tones[rung.tier]}
                  />
                );
              })}
            </div>
          )}
        </Panel>

        <Panel eyebrow="Natural Language Understanding" title="Intent Distribution & Confidence">
          {data.intents.length === 0 ? (
            <Empty title="No Intents Classified" hint="Intent distribution renders once queries have been processed." />
          ) : (
            <div className="space-y-3.5">
              {data.intents.map((row) => (
                <Bar
                  key={row.intent}
                  label={row.intent.toLowerCase().replace(/_/g, " ")}
                  hint={`Avg confidence: ${pct(row.avg_confidence)}`}
                  value={row.count}
                  share={volume.cases ? row.count / volume.cases : 0}
                  tone={row.avg_confidence >= 0.7 ? "neutral" : "warn"}
                />
              ))}
            </div>
          )}
        </Panel>

        <Panel eyebrow="Escalations & SLA" title="Team SLA Compliance">
          {data.escalations.length === 0 ? (
            <Empty title="Zero Escalations" hint="Tier-3 cases requiring human action appear here." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="label-micro border-b border-slate-100">
                  <tr>
                    <th className="pb-2.5 text-slate-500">Escalation Type</th>
                    <th className="pb-2.5 text-slate-500">Owner Team</th>
                    <th className="pb-2.5 text-right text-slate-500">Open</th>
                    <th className="pb-2.5 text-right text-slate-500">SLA Breached</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-mono">
                  {data.escalations.map((row) => (
                    <tr key={`${row.type}-${row.owner_team}`} className="hover:bg-slate-50/60">
                      <td className="py-2.5 font-semibold text-slate-800">{row.type.replace(/_/g, " ")}</td>
                      <td className="py-2.5 text-slate-600">{row.owner_team.replace(/_/g, " ")}</td>
                      <td className="py-2.5 text-right font-bold text-slate-800">{row.open}</td>
                      <td className="py-2.5 text-right font-bold">
                        <span className={row.sla_breached ? "rounded bg-rose-100 px-1.5 py-0.5 text-rose-800" : "text-slate-400"}>
                          {row.sla_breached}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel eyebrow="Human Governance" title="Draft Review Outcomes">
          <div className="grid grid-cols-3 gap-3 border-b border-slate-100 pb-4">
            <Mini label="Approved as Drafted" value={review.approved} tone="good" />
            <Mini label="Edited & Sent" value={review.edited} tone="neutral" />
            <Mini label="Rejected" value={review.rejected} tone="bad" />
          </div>
          {review.reasons.length === 0 ? (
            <p className="mt-4 text-xs text-slate-500 leading-relaxed">
              No draft rejections recorded yet. Categorized rejections highlight which agent prompt requires fine-tuning.
            </p>
          ) : (
            <div className="mt-4 space-y-3">
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
            <div className="mt-4 flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 border border-amber-200/80 font-mono text-xs font-semibold text-amber-800">
              <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
              {review.pending} drafts awaiting human staff approval
            </div>
          )}
        </Panel>

        <Panel eyebrow="System Efficiency" title="Cost & Response Latency">
          <div className="grid grid-cols-3 gap-3 border-b border-slate-100 pb-4">
            <Mini label="Avg Cost / Case" value={`$${cost.per_case_usd.toFixed(5)}`} tone="good" />
            <Mini label="P95 Latency" value={`${(latency.p95_ms / 1000).toFixed(1)}s`} tone={latency.within_target ? "good" : "bad"} />
            <Mini label="Total Tokens" value={cost.tokens.toLocaleString()} tone="neutral" />
          </div>
          <p className="mt-3 font-mono text-micro text-slate-500 leading-relaxed">
            Target P95 &lt; {(latency.target_p95_ms / 1000).toFixed(1)}s · Median response time: {formatDuration(latency.median_response_seconds)}
          </p>
          {cost.by_intent.length > 0 && (
            <div className="mt-4 space-y-3">
              {cost.by_intent.slice(0, 5).map((row) => (
                <Bar
                  key={row.intent}
                  label={row.intent.toLowerCase().replace(/_/g, " ")}
                  hint={`$${row.avg_cost_usd.toFixed(5)} avg · ${row.cases} cases`}
                  value={Number(row.cost_usd.toFixed(4))}
                  share={cost.total_usd ? row.cost_usd / cost.total_usd : 0}
                  tone="neutral"
                />
              ))}
            </div>
          )}
        </Panel>

        <Panel eyebrow="Maintenance Operations" title="Field Ticket SLA Metrics">
          <div className="grid grid-cols-2 gap-4">
            <Mini label="Active Tickets" value={maintenance.tickets} />
            <Mini
              label="SLA Breached"
              value={maintenance.sla_breached}
              tone={maintenance.sla_breached > 0 ? "bad" : "good"}
            />
            <Mini label="P1 Critical Tickets" value={maintenance.p1} tone={maintenance.p1 > 0 ? "warn" : "neutral"} />
            <Mini label="Warranty Claims" value={maintenance.warranty_flagged} />
          </div>
          <div className="mt-5 border-t border-slate-100 pt-4">
            <div className="label-micro mb-3 text-slate-500 font-semibold">Confidence Band Breakdown</div>
            <div className="space-y-2.5">
              {confidence.bands.map((band) => (
                <Bar
                  key={band.band}
                  label={`Confidence Range ${band.band}`}
                  value={band.count}
                  share={volume.cases ? band.count / volume.cases : 0}
                  tone={band.band === "<0.5" || band.band === "0.5-0.7" ? "warn" : "good"}
                />
              ))}
            </div>
          </div>
        </Panel>
      </div>

      {/* Schedule & Leads Section */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel eyebrow="Construction Schedule" title="Delayed Milestone Tracker">
          {data.delayed_milestones.length === 0 ? (
            <Empty title="Schedule On Track" hint="All active tower construction milestones are meeting planned targets." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="label-micro border-b border-slate-100">
                  <tr>
                    <th className="pb-2.5 text-slate-500">Tower</th>
                    <th className="pb-2.5 text-slate-500">Milestone</th>
                    <th className="pb-2.5 text-slate-500">Planned Date</th>
                    <th className="pb-2.5 text-right text-slate-500">Schedule Slip</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-mono">
                  {data.delayed_milestones.map((row) => (
                    <tr key={`${row.tower}-${row.milestone}`} className="hover:bg-slate-50/60">
                      <td className="py-2.5 font-bold text-slate-900">{row.tower}</td>
                      <td className="py-2.5 text-slate-600">{row.milestone}</td>
                      <td className="py-2.5 text-slate-500">{row.planned_date}</td>
                      <td className="py-2.5 text-right">
                        <span
                          className={`rounded px-2 py-0.5 font-bold ${
                            row.slip_days >= 14
                              ? "bg-rose-100 text-rose-800"
                              : "bg-amber-100 text-amber-800"
                          }`}
                        >
                          +{row.slip_days}d slip
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel eyebrow="Sales CRM Pipeline" title="High-Priority Leads Due Today">
          {data.leads_due_today.length === 0 ? (
            <Empty title="No Pending Follow-ups" hint="All high-score sales leads have been contacted." />
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.leads_due_today.map((lead) => (
                <li key={lead.lead_id} className="flex items-center justify-between gap-4 py-3">
                  <div className="min-w-0">
                    <p className="truncate text-xs font-semibold text-ink font-display">{lead.name}</p>
                    <p className="font-mono text-micro text-slate-500 mt-0.5">
                      {lead.next_action ?? "No action set"}
                      {lead.next_action_due ? ` · due ${lead.next_action_due}` : ""}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <span className="inline-flex items-center rounded-full bg-brand-50 px-2.5 py-0.5 font-mono text-xs font-bold text-brand-700 border border-brand-200">
                      Score: {lead.score}
                    </span>
                    <p className="font-mono text-micro text-slate-400 mt-1">
                      {lead.days_since_contact}d since contact
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}

type BarTone = "good" | "neutral" | "warn" | "bad";

const TONE_BAR: Record<BarTone, string> = {
  good: "bg-emerald-500",
  neutral: "bg-blue-500",
  warn: "bg-amber-500",
  bad: "bg-rose-500",
};

const TONE_TEXT: Record<BarTone, string> = {
  good: "text-emerald-700",
  neutral: "text-slate-800",
  warn: "text-amber-700",
  bad: "text-rose-700",
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

function MetricCard({
  label,
  value,
  detail,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: string;
  detail: string;
  icon: ReactNode;
  tone?: BarTone;
}) {
  return (
    <div className="sheet ticked p-5 hover:border-slate-300 transition-all hover:shadow-md">
      <div className="flex items-center justify-between">
        <span className="label-micro font-semibold">{label}</span>
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-50 border border-slate-100">
          {icon}
        </div>
      </div>
      <p className={`mt-3 font-display text-3xl font-bold tracking-tight ${TONE_TEXT[tone]}`}>{value}</p>
      <p className="mt-1.5 text-xs text-slate-500 leading-relaxed font-sans">{detail}</p>
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
    <section className="sheet p-5 bg-white shadow-sheet">
      <SheetHeading eyebrow={eyebrow} title={title} />
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Mini({ label, value, tone = "neutral" }: { label: string; value: number | string; tone?: BarTone }) {
  return (
    <div>
      <div className="label-micro font-semibold">{label}</div>
      <p className={`mt-1 font-mono text-xl font-bold ${TONE_TEXT[tone]}`}>{value}</p>
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
        <span className="text-xs font-semibold text-slate-800 capitalize font-sans">{label}</span>
        <span className="font-mono text-xs font-bold text-slate-700">{value}</span>
      </div>
      <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full transition-all duration-300 ${TONE_BAR[tone]}`}
          style={{ width: `${Math.max(share * 100, value > 0 ? 2 : 0)}%` }}
        />
      </div>
      {hint && <p className="mt-1 font-mono text-micro text-slate-400">{hint}</p>}
    </div>
  );
}
