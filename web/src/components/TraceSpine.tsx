// The audit "spine": one vertical line, one node per pipeline step, with the
// prompt and policy version that produced it. Reading top to bottom reconstructs
// the decision — which is the whole claim the audit trail makes.

import type { TraceStep } from "../api/types";

const NODE_TONE: Record<string, string> = {
  masking: "bg-steel",
  classification: "bg-signal-blue",
  router: "bg-steel-dark",
  risk_engine: "bg-signal-amber",
  escalation: "bg-signal-red",
  gate: "bg-ink",
  human_review: "bg-signal-green",
  review_queue: "bg-signal-amber",
};

export function TraceSpine({ steps }: { steps: TraceStep[] }) {
  if (!steps.length) {
    return <p className="text-sm text-steel-dark">No trace rows were written for this case.</p>;
  }
  return (
    <ol className="relative ml-2 border-l border-ink-line/30">
      {steps.map((step) => (
        <li key={step.seq} className="relative pb-5 pl-6">
          <span
            className={`absolute -left-[5px] top-1.5 h-2.5 w-2.5 rounded-full ${
              NODE_TONE[step.agent] ?? "bg-steel-light"
            }`}
          />
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="font-mono text-xs font-medium uppercase tracking-wider text-ink">
              {step.agent}
            </span>
            {step.decision && (
              <span className="font-mono text-micro text-steel-dark">{step.decision}</span>
            )}
            {step.confidence !== null && (
              <span className="font-mono text-micro text-steel">
                conf {Math.round(step.confidence * 100)}%
              </span>
            )}
            {step.risk_tier !== null && (
              <span className="font-mono text-micro text-signal-amber">tier {step.risk_tier}</span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 font-mono text-micro text-steel">
            {step.prompt_version && <span>prompt {step.prompt_version}</span>}
            {step.policy_version && <span>policy {step.policy_version}</span>}
            {step.model && <span>model {step.model}</span>}
            <span>{step.latency_ms} ms</span>
            {step.tokens > 0 && <span>{step.tokens} tok</span>}
            {step.human_actor && <span className="text-signal-green">by {step.human_actor}</span>}
          </div>
          {step.sources.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {[...new Set(step.sources)].map((source) => (
                <span
                  key={source}
                  className="border border-paper-edge bg-paper px-1.5 py-0.5 font-mono text-micro text-steel-dark"
                >
                  {source}
                </span>
              ))}
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}
