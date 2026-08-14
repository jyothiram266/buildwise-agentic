// Wire types, mirroring api/schemas/responses.py. Kept hand-written rather than
// generated so the frontend fails to compile when the API contract changes.

export type Citation = {
  source_name: string;
  source_id: string;
  section: string | null;
  effective_date: string | null;
  is_stale: boolean;
};

export type Finding = {
  agent: string;
  status: "ok" | "insufficient_data" | "conflict" | "error";
  summary: string;
  confidence: number;
  internal_only: boolean;
  citations: Citation[];
  structured: Record<string, unknown>;
};

export type CaseResponse = {
  case_id: string;
  intent: string | null;
  secondary_intent: string | null;
  risk_tier: number | null;
  status: string;
  mode: "auto_send" | "draft_for_approval" | "acknowledgement_only" | "refuse" | null;
  text: string | null;
  citations: Citation[];
  confidence: number | null;
  findings: Finding[];
  escalation: Record<string, unknown> | null;
  degraded: boolean;
  degraded_reasons: string[];
  node_log: string[];
  latency_ms: number;
  cost_usd: number;
  cost_tokens: number;
  masked_entities: string[];
};

export type Actor = {
  actor_id: string;
  display_name: string;
  role: string;
  booking_ids: string[];
  unit_ids: string[];
  project_ids: string[];
  work_package_ids: string[];
};

export type ReviewItem = {
  review_id: string;
  case_id: string;
  risk_tier: number;
  audience: string;
  original_request: string;
  reasoning_summary: string;
  citations: Citation[];
  proposed_response: string;
  confidence: number;
  sla_due: string | null;
  status: string;
  created_at: string;
  sla?: {
    due_at: string;
    remaining_minutes: number;
    breached: boolean;
    ageing_bucket: string;
  };
};

export type CaseSummary = {
  case_id: string;
  actor_id: string;
  role: string;
  channel: string;
  intent: string | null;
  risk_tier: number | null;
  status: string;
  masked_input: string;
  response_mode: string | null;
  confidence: number | null;
  degraded: boolean;
  latency_ms: number;
  cost_usd: number;
  created_at: string;
};

export type TraceStep = {
  seq: number;
  agent: string;
  decision: string | null;
  confidence: number | null;
  risk_tier: number | null;
  prompt_version: string | null;
  policy_version: string | null;
  model: string | null;
  sources: string[];
  latency_ms: number;
  tokens: number;
  cost_usd: number;
  human_actor: string | null;
  output: Record<string, unknown>;
  at: string;
};

// Typed rather than Record<string, unknown>. Loose typing here was a real bug:
// every field came out as `unknown`, and `unknown && <JSX>` is not a valid
// ReactNode, so the build failed on the one place that rendered a field
// conditionally. Naming the fields also means a backend rename breaks the build
// instead of silently rendering "undefined".
export type CaseRecord = {
  case_id?: string;
  actor_id?: string;
  role?: string;
  channel?: string;
  intent?: string | null;
  secondary_intent?: string | null;
  sentiment?: string | null;
  risk_tier?: number | null;
  status?: string;
  masked_input?: string;
  response_mode?: string | null;
  response_text?: string | null;
  confidence?: number | null;
  degraded?: boolean;
  cost_tokens?: number;
  cost_usd?: number;
  latency_ms?: number;
  created_at?: string;
};

export type EscalationRecord = {
  esc_id?: string;
  type?: string;
  owner_team?: string;
  sla_hours?: number;
  sla_due?: string;
  status?: string;
  assigned_to?: string | null;
  brief?: string | null;
};

export type HumanReviewRecord = {
  review_id?: string;
  status?: string;
  action?: string | null;
  acted_by?: string | null;
  acted_at?: string | null;
  rejection_reason?: string | null;
  was_edited?: boolean;
};

export type Replay = {
  case_id: string;
  found: boolean;
  case: CaseRecord;
  steps: TraceStep[];
  versions: { prompts: string[]; policies: string[]; models: string[] };
  sources_used: string[];
  escalation: EscalationRecord | null;
  human_review: HumanReviewRecord | null;
  reproducible: boolean;
};

export type Dashboard = {
  window_days: number;
  volume: {
    cases: number;
    answered: number;
    awaiting_approval: number;
    escalated: number;
    failed: number;
    degraded: number;
    automation_rate: number;
    escalation_rate: number;
    refusal_rate: number;
  };
  latency: {
    avg_ms: number;
    median_ms: number;
    p95_ms: number;
    target_p95_ms: number;
    within_target: boolean;
    median_response_seconds: number;
  };
  cost: {
    total_usd: number;
    tokens: number;
    per_case_usd: number;
    by_intent: { intent: string; cost_usd: number; cases: number; avg_cost_usd: number }[];
  };
  confidence: { average: number; bands: { band: string; count: number }[] };
  risk_tiers: { tier: number; count: number }[];
  intents: { intent: string; count: number; avg_confidence: number }[];
  escalations: {
    type: string;
    owner_team: string;
    count: number;
    open: number;
    sla_breached: number;
  }[];
  human_review: {
    decided: number;
    approved: number;
    edited: number;
    rejected: number;
    override_rate: number;
    target: number;
    reasons: { reason: string; count: number }[];
    pending: number;
  };
  maintenance: { tickets: number; sla_breached: number; p1: number; warranty_flagged: number };
  // FR-GOV-4 names six panels. These three were added to the API and initially had
  // no UI, which meant the requirement was only half met.
  delayed_milestones: {
    project: string;
    tower: string;
    milestone: string;
    planned_date: string;
    actual_date: string | null;
    status: string;
    slip_days: number;
  }[];
  leads_due_today: {
    lead_id: string;
    name: string;
    score: number;
    stage: string;
    next_action: string | null;
    next_action_due: string | null;
    days_since_contact: number;
  }[];
  escalation_ageing: { bucket: string; count: number; sla_breached: number }[];
  kb_gaps: { query: string; role: string; hits: number }[];
  targets: Record<string, number>;
};
