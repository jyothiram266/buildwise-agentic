# System Architecture
## Agentic AI Real Estate & Construction Support System
**Client (Case Study):** BuildWise Realty & Construction Group
**Document version:** 1.0
**Companion to:** `BuildWise_PRD.md`

---

## 1. Architectural Principles

Five decisions shape everything below.

1. **Deterministic where possible, generative where necessary.** Routing, RBAC, priority matrices, and SLA clocks are code, not prompts. The model is used for understanding language and synthesising prose — not for enforcing policy.
2. **Authorisation below the model.** The retrieval layer filters by user scope *before* documents reach the context window. A prompt cannot talk its way into another customer's data because the data never enters the prompt.
3. **Narrow agents, explicit contracts.** Each agent has one job, typed input, typed output. This is what makes failures diagnosable and the audit trail meaningful.
4. **Uncertainty is a first-class output.** Every agent emits a confidence score. Low confidence routes to a human rather than producing a plausible guess.
5. **Connector abstraction from day one.** Mock CRM and real CRM implement the same interface, so the capstone prototype is a swap away from integration rather than a rewrite.

---

## 2. High-Level Layered Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — EXPERIENCE                                                    │
│  Customer Web Chat │ Broker Portal │ Staff Console │ Leadership Dashboard│
│  Email/Form Intake │ Call-Transcript Upload │ Contractor Portal          │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │ HTTPS / REST + WebSocket (streaming)
┌────────────────────────────────▼─────────────────────────────────────────┐
│  LAYER 2 — API GATEWAY & IDENTITY                                        │
│  AuthN (JWT) │ Role Resolution │ Rate Limiting │ Input Sanitisation       │
│  Channel Normaliser → canonical Case object                              │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────────────┐
│  LAYER 3 — AI ORCHESTRATION (state-machine graph)                        │
│                                                                          │
│   ┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐   │
│   │  Classification │───▶│  Router / Planner│───▶│  Risk-Tier Engine│   │
│   └─────────────────┘    └────────┬─────────┘    └────────┬─────────┘   │
│                                   │                        │             │
│        ┌──────────────┬───────────┼──────────┬─────────────┤             │
│        ▼              ▼           ▼          ▼             ▼             │
│   ┌─────────┐  ┌───────────┐ ┌────────┐ ┌────────┐  ┌──────────┐        │
│   │Property │  │Constructn │ │  Docs  │ │Maintnce│  │Contractor│        │
│   │  Agent  │  │  Agent    │ │ Agent  │ │ Agent  │  │  Agent   │        │
│   └────┬────┘  └─────┬─────┘ └───┬────┘ └───┬────┘  └────┬─────┘        │
│        └─────────────┴───────────┴──────────┴────────────┘              │
│                                   │                                      │
│                    ┌──────────────▼──────────────┐                       │
│                    │  Escalation & Risk Agent    │                       │
│                    └──────────────┬──────────────┘                       │
│                    ┌──────────────▼──────────────┐                       │
│                    │  Response Generation Agent  │                       │
│                    └──────────────┬──────────────┘                       │
└───────────────────────────────────┼──────────────────────────────────────┘
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌───────────────────────────────┐   ┌──────────────────────────────────────┐
│ LAYER 4 — KNOWLEDGE/RETRIEVAL │   │ LAYER 5 — INTEGRATION (connectors)   │
│ Vector Store (pgvector)       │   │ CRM │ Project Mgmt │ Payments        │
│ Hybrid Search (BM25 + dense)  │   │ DMS │ Ticketing                     │
│ Reranker │ Chunk Metadata     │   │ Adapter Interface + Retry + Cache    │
│ ACL Pre-filter │ Freshness    │   │ (mock impls for capstone)            │
└───────────────────────────────┘   └──────────────────────────────────────┘
                    │                               │
┌───────────────────▼───────────────────────────────▼──────────────────────┐
│  LAYER 6 — GOVERNANCE & DATA                                             │
│  Audit Log (append-only) │ Human Review Queue │ Policy & Prompt Registry │
│  PII Masking Service │ Postgres (cases, tickets, leads) │ Redis (session)│
│  Observability: traces, cost, confidence, escalation & override metrics  │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Orchestration Design

### 3.1 Pattern
A **supervisor-with-graph** pattern: a deterministic router selects which specialist agents to invoke based on the classified intent, then a mandatory pipeline (Risk → Response) closes every path. Specialists never call each other directly; all coordination passes through shared graph state. This keeps the execution trace linear and auditable.

### 3.2 Canonical State Object
```json
{
  "case_id": "BW-2026-08-014237",
  "channel": "web_chat",
  "actor": { "id": "CUST-4471", "role": "customer", "scope": ["booking:BK-9912"] },
  "raw_input": "Why has Tower B possession moved to March?",
  "classification": {
    "intent": "COMPLAINT_ESCALATION",
    "secondary_intent": "CONSTRUCTION_STATUS",
    "confidence": 0.91,
    "entities": { "project": "Aurora Heights", "tower": "B", "urgency": "high" },
    "sentiment": "negative"
  },
  "agent_outputs": [],
  "retrieved_sources": [],
  "risk_tier": 3,
  "escalation": { "required": true, "owner_team": "customer_relations", "sla_hours": 24 },
  "response": { "mode": "acknowledgement_only", "text": null, "citations": [] },
  "trace": [],
  "cost_tokens": 0
}
```

### 3.3 Execution Sequence
1. **Ingest** — normalise channel payload, mask PII, create `Case`, persist.
2. **Classify** — intent + entities + confidence. Below threshold → human triage node, exit.
3. **Plan** — router selects specialists (one or several, run in parallel where independent).
4. **Retrieve & Act** — specialists query KB and connectors; each returns typed findings + citations + confidence.
5. **Assess Risk** — Escalation Agent evaluates full state against the risk taxonomy; assigns tier.
6. **Generate** — Response Agent composes output for the audience, constrained by tier.
7. **Gate** — Tier 0/1 auto-send; Tier 2 to approval queue; Tier 3 acknowledgement + escalation brief.
8. **Log & Close** — append immutable trace; update dashboards; start SLA clocks.

### 3.4 Failure Handling
| Failure | Behaviour |
|---|---|
| Connector timeout | Retry with backoff (2 attempts), then respond with partial data explicitly labelled, or route to human |
| Empty retrieval | Refuse to answer factually; offer human handoff; log KB gap |
| Conflicting sources | Escalate; never silently pick one |
| Model output fails schema validation | One repair attempt, then human triage |
| Any agent exception | Case moves to human queue with error context — never a silent drop |

---

## 4. Knowledge and Retrieval Layer

### 4.1 Corpus
| Collection | Contents | Freshness Window | Audience Scope |
|---|---|---|---|
| `property_catalog` | Brochures, floor plans, amenities, location detail | 90 days | public |
| `pricing_sheets` | Approved price lists with effective dates | 7 days | public / broker |
| `project_reports` | Weekly site progress, inspection results, milestone logs | 7 days | internal (customer-safe derivative generated) |
| `doc_checklists` | Stage-wise documentation requirements | 180 days | customer / internal |
| `policies` | Maintenance SLA, warranty terms, escalation matrix, payment-milestone policy | 365 days | scoped by role |
| `faq` | Curated approved Q&A | 90 days | public |

### 4.2 Pipeline
`Ingest → PII mask → Chunk (semantic, 400–700 tokens, section-aware) → Embed → Index (dense + BM25)`

Retrieval: **ACL pre-filter → hybrid search (k=20) → cross-encoder rerank → top-5 into context**, each chunk carrying `source_name`, `section`, `effective_date`, `audience_scope`, `confidence`.

### 4.3 Structured vs. Unstructured Split
A hard rule: **numbers come from systems of record, prose comes from the knowledge base.** Prices, unit availability, payment balances, milestone dates, and ticket status are fetched via connectors as typed fields. The knowledge base supplies explanation and procedure. This is the primary defence against fabricated figures — the model is never asked to recall a number, only to present one it was handed.

---

## 5. Integration Layer

### 5.1 Connector Interface (uniform contract)
```python
class SystemConnector(Protocol):
    def health(self) -> Health: ...
    def query(self, request: TypedQuery, scope: AccessScope) -> TypedResult: ...
    def write(self, action: TypedAction, scope: AccessScope,
              approval: ApprovalToken | None) -> WriteResult: ...
```
Write operations require an `ApprovalToken` whenever the action's risk tier is 2 or above. The connector — not the agent — enforces this.

### 5.2 Systems and Operations
| Connector | Reads | Writes (capstone: mock) |
|---|---|---|
| **CRM** | Lead, customer, booking, contact history, follow-up status | Create lead, log interaction, set follow-up |
| **Project Management** | Milestones, planned vs. actual dates, site reports, inspections | Log blocker, attach summary |
| **Payments** | Milestone schedule, paid/pending, receipts | *No writes — read-only by design* |
| **Document Management** | Submitted docs, status, expiry | Upload metadata, flag missing |
| **Ticketing** | Ticket status, SLA, assignment history | Create ticket, set priority, route |

Payments is deliberately read-only. No agent path can move money.

---

## 6. Governance Layer

### 6.1 RBAC Scope Model
| Role | Data Scope |
|---|---|
| `public_lead` | Published catalog, pricing, FAQ |
| `customer` | Own booking, own payments, own documents, customer-safe project view |
| `resident` | Own unit, own tickets, community notices |
| `broker` | Partner inventory availability, brochures, own commission records |
| `contractor` | Own work package, own submissions |
| `sales_staff` | All leads, catalog, pricing; no legal or payment-dispute records |
| `site_engineer` | Assigned projects, full technical reports |
| `legal_finance` | Documents, payments, disputes across customers |
| `manager` | Read-all + dashboards + approval authority |

Scope resolves at authentication and is passed to every retrieval and connector call as an immutable `AccessScope`.

### 6.2 Audit Record
Every agent invocation appends: `case_id`, `agent`, `prompt_version`, `policy_version`, `model`, `inputs_hash`, `retrieved_source_ids`, `output`, `confidence`, `risk_tier`, `decision`, `human_actor`, `latency_ms`, `tokens`, `timestamp`. Append-only, so any past response is reproducible with the exact configuration that produced it.

### 6.3 Human Review Queue
Tier 2 drafts and Tier 3 escalations surface with: original request, agent reasoning summary, cited sources, proposed response, confidence, SLA remaining. Actions: **approve**, **edit and send**, **reject with reason**, **reassign**. Rejection reasons are structured and feed the evaluation backlog — the override rate is a product metric, not just an operational one.

### 6.4 Prompt-Injection Defences
- All ingested documents and user text treated as untrusted data, never as instructions.
- Tool invocation permitted only from the deterministic router, never from model-generated text alone.
- Output schema validation before any write.
- Scope enforced below the model, so injection cannot widen data access.
- Instruction-like patterns in ingested content flagged for review.

---

## 7. Technology Stack

| Concern | Choice | Rationale |
|---|---|---|
| Orchestration | Python + LangGraph (or equivalent state-graph framework) | Explicit state machine, checkpointing, resumability, inspectable traces |
| API | FastAPI | Async, Pydantic typing aligns with typed agent contracts |
| Models | Large model for synthesis and escalation reasoning; small/fast model for classification and extraction | Cost and latency control at the highest-volume step |
| Vector store | PostgreSQL + pgvector | One datastore for relational and vector data; ACL filters run as SQL predicates |
| Search | Hybrid BM25 + dense, cross-encoder rerank | Exact-match matters for unit IDs and project names |
| Cache / session | Redis | Conversation state, connector response cache |
| Frontend | React + TypeScript + Tailwind | Fast prototype iteration; shared components across chat and dashboard |
| Observability | OpenTelemetry + LLM tracing | Per-agent latency, cost, confidence distribution |
| Evaluation | Pytest-based harness + labelled dataset | Regression gate on every prompt change |
| Deployment | Docker Compose (capstone) → container platform | Reproducible demo environment |

---

## 8. Data Model (Core Entities)

```
Project (project_id, name, city, type, launch_date, planned_possession, status)
  └─ Tower (tower_id, project_id, name, floors, units_total)
      └─ Unit (unit_id, tower_id, config, carpet_area, floor, status, price_ref)

Customer (customer_id, name, contact, kyc_status, created_at)
  └─ Booking (booking_id, customer_id, unit_id, stage, agreement_status, possession_date)
      ├─ PaymentMilestone (milestone_id, booking_id, label, amount, due_date, paid_on)
      └─ Document (doc_id, booking_id, type, status, submitted_on, expires_on)

Milestone (milestone_id, project_id, tower_id, name, planned_date, actual_date, pct_complete)
  └─ SiteReport (report_id, project_id, week_of, author, raw_note, internal_summary,
                 customer_summary, approval_status)

Blocker (blocker_id, project_id, vendor_id, category, description, impacted_milestones[],
         severity, raised_on, resolved_on)

Case (case_id, actor_id, channel, intent, entities, risk_tier, status, created_at, closed_at)
  ├─ AgentTrace (trace_id, case_id, agent, inputs, output, confidence, sources[], ts)
  └─ Escalation (esc_id, case_id, type, owner_team, sla_due, brief, resolution)

Ticket (ticket_id, unit_id, category, priority, assigned_team, sla_due, status,
        warranty_flag)
Lead (lead_id, contact, interest_config, budget, city, score, last_contact, next_action)
```

---

## 9. Sequence Walkthrough: Possession-Date Escalation (UJ-4)

```
Customer ──▶ Gateway: "Why has Tower B possession moved to March?"
Gateway   ──▶ AuthN → role=customer, scope=[booking:BK-9912] → Case created, PII masked
          ──▶ Orchestrator

Classification Agent
   intent=COMPLAINT_ESCALATION, secondary=CONSTRUCTION_STATUS
   entities={project:Aurora Heights, tower:B}, sentiment=negative, confidence=0.91

Router → [Construction Agent, Documentation-skip, Payments-skip] + mandatory Risk node

Construction Agent
   → PM connector: milestones(project=Aurora Heights, tower=B)   [typed fields]
   → KB: project_reports, scope=internal, ACL-filtered
   ← planned 2026-12, revised 2027-03 (approved record exists), slippage=3mo,
     cause=approval delay (internal-only detail)

Escalation & Risk Agent
   Triggers matched: possession-date change + negative sentiment + customer dispute
   → risk_tier=3, owner_team=customer_relations, sla=24h
   → Escalation brief: history, approved date record, slippage cause, recommended action

Response Agent  (constrained: Tier 3 → acknowledgement only)
   Customer receives: acknowledgement + confirmation the revised date is an approved
   record + named owner + 24h response commitment. No cause speculation, no new
   commitment, no internal detail.

Governance
   Escalation queued with brief │ SLA clock started │ full trace appended │
   dashboard escalation count and ageing updated
```

Note what did *not* happen: the system had the internal cause in context and did not disclose it, and did not attempt to resolve a dispute. That restraint is the architecture working as designed.

---

## 10. Evaluation Architecture

| Test Layer | Dataset | Gate |
|---|---|---|
| Intent classification | 200–300 labelled requests across 9 classes, incl. ambiguous and multi-intent | ≥ 90% accuracy |
| Entity extraction | Same set, annotated spans | F1 ≥ 0.85 |
| Retrieval quality | 100 queries with relevance judgments | Recall@5 ≥ 0.90 |
| Groundedness | 100 generated responses, claim-level check | ≥ 95% supported; 0 fabricated numbers |
| Escalation routing | 80 cases incl. legal, safety, payment-dispute, low-confidence | Recall ≥ 95%, precision ≥ 80% |
| Maintenance routing | 100 complaints across 9 categories | ≥ 90% category + priority accuracy |
| RBAC / leakage | Adversarial cross-customer and cross-role probes | 0 leaks |
| Injection resistance | Malicious instructions embedded in site reports and user text | 0 successful tool or scope violations |

The eval harness runs as a regression gate: no prompt or policy change ships without it passing.

---

## 11. Deployment View (Capstone)

```
┌─ Docker Compose ────────────────────────────────────────────┐
│  web (React, :3000)                                         │
│  api (FastAPI + orchestrator, :8000)                        │
│  postgres + pgvector (:5432)   ← cases, entities, embeddings│
│  redis (:6379)                 ← sessions, connector cache  │
│  mock-connectors (:8100)       ← CRM/PM/Pay/DMS/Ticketing   │
│  otel-collector + trace UI     ← observability              │
└─────────────────────────────────────────────────────────────┘
        └── external: LLM API (network-isolated key handling)
```

Post-capstone path: replace `mock-connectors` with real adapters implementing the same `SystemConnector` protocol; move to managed Postgres and a container platform; add tenant isolation.

---

## 12. Design Decisions and Trade-offs

| Decision | Alternative Considered | Why This Way |
|---|---|---|
| Supervisor graph with deterministic routing | Fully autonomous agent-to-agent negotiation | Auditability and predictability matter more than flexibility in a regulated, money-adjacent domain |
| Numbers from connectors only | Let the model read pricing PDFs | Eliminates the highest-consequence hallucination class outright |
| RBAC below the model | Prompt-level instructions to respect scope | Instructions can be manipulated; a SQL predicate cannot be talked out of |
| Payments read-only | Allow approved payment writes | No plausible capstone benefit justifies the risk surface |
| Two summaries from one source (internal + customer) | One summary, redact on output | Separate generation prevents accidental internal-detail leakage |
| pgvector over a dedicated vector DB | Pinecone / Weaviate | ACL filters and relational joins in one query; simpler prototype ops |
| Escalation recall over precision | Balanced F1 | Asymmetric cost: a missed legal escalation is not comparable to a wasted review |

---

*Companion document: `BuildWise_PRD.md`*
