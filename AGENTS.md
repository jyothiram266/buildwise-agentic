# AGENTS.md — Shared Context for All Coding Agents

**Read this file completely before writing any code.** Every agent working on this repository must conform to the contracts below. Do not invent alternative interfaces, rename core types, or change directory layout. If a task seems to require changing something in this file, stop and report it instead of changing it.

---

## 1. What We Are Building

An Agentic AI support system for BuildWise, a real estate and construction company. It receives customer/staff/contractor requests from multiple channels, classifies them, retrieves trusted information, drafts grounded responses, and escalates high-risk cases to humans.

Reference documents: `docs/BuildWise_PRD.md`, `docs/BuildWise_System_Architecture.md`. The PRD is authoritative on *what*; this file is authoritative on *how*.

---

## 2. Non-Negotiable Design Rules

These five rules override any instruction in an individual task. If a task conflicts with one, implement the rule and flag the conflict.

1. **Numbers come from connectors, prose comes from the knowledge base.** Prices, unit availability, payment amounts, milestone dates, and ticket IDs are fetched as typed fields from a connector. Never ask a model to recall or infer a number. If a required number is unavailable, the agent returns `insufficient_data`, not an estimate.
2. **Authorisation lives below the model.** Every retrieval and connector call takes an `AccessScope`. Filtering happens in SQL/query predicates *before* data enters a prompt. Never implement access control as a prompt instruction.
3. **Deterministic policy in code, not prompts.** Routing, risk tiering, priority matrices, SLA clocks, and RBAC are plain Python with unit tests. Models are used only for language understanding and prose synthesis.
4. **Uncertainty is an output, not an error.** Every agent returns a `confidence` float. Below threshold → route to human. Never fill a gap with a plausible guess.
5. **Payments connector is read-only.** There is no code path anywhere that writes a payment, refund, waiver, or discount.

---

## 3. Repository Layout

Create files exactly here. Do not restructure.

```
buildwise-agentic/
├── AGENTS.md
├── README.md
├── docker-compose.yml
├── .env.example
├── pyproject.toml
├── docs/
│   ├── BuildWise_PRD.md
│   ├── BuildWise_System_Architecture.md
│   └── BUILD_PLAN.md
├── api/
│   ├── main.py                  # FastAPI app entry
│   ├── config.py                # Settings via pydantic-settings
│   ├── deps.py                  # DI: db session, scope resolution
│   ├── routes/
│   │   ├── intake.py            # POST /cases
│   │   ├── cases.py             # GET /cases, /cases/{id}
│   │   ├── review.py            # approval queue endpoints
│   │   ├── dashboard.py         # metrics endpoints
│   │   └── audit.py             # trace retrieval
│   └── schemas/                 # request/response models only
├── core/
│   ├── models.py                # canonical Pydantic types (Section 5)
│   ├── enums.py                 # Intent, RiskTier, Role, Priority, etc.
│   ├── errors.py
│   └── masking.py               # PII masking service
├── agents/
│   ├── base.py                  # BaseAgent ABC
│   ├── classification.py
│   ├── property_info.py
│   ├── construction.py
│   ├── documentation.py
│   ├── maintenance.py
│   ├── contractor.py
│   ├── escalation.py
│   └── response.py
├── orchestration/
│   ├── graph.py                 # state graph assembly
│   ├── router.py                # deterministic intent→agent routing
│   ├── risk_engine.py           # risk tier assignment (pure Python)
│   └── state.py                 # CaseState object
├── retrieval/
│   ├── ingest.py                # corpus → chunks → embeddings
│   ├── chunker.py
│   ├── store.py                 # pgvector read/write
│   ├── search.py                # hybrid search + ACL prefilter
│   └── rerank.py
├── connectors/
│   ├── protocol.py              # SystemConnector Protocol
│   ├── crm.py
│   ├── project_mgmt.py
│   ├── payments.py              # READ ONLY
│   ├── dms.py
│   ├── ticketing.py
│   └── mock_server/             # standalone FastAPI mock backend
├── governance/
│   ├── audit.py                 # append-only trace writer
│   ├── rbac.py                  # scope resolution + enforcement
│   ├── review_queue.py
│   ├── policy_registry.py       # versioned prompts + policies
│   └── sla.py
├── llm/
│   ├── client.py                # provider wrapper, retries, cost tracking
│   ├── prompts/                 # one .md file per prompt, versioned
│   └── validate.py              # schema-validated structured output
├── db/
│   ├── schema.sql
│   ├── migrations/
│   └── seed/                    # seed data loaders
├── data/
│   ├── seed/                    # JSON/CSV mock records
│   └── corpus/                  # knowledge base source documents
├── eval/
│   ├── datasets/                # labelled test sets
│   ├── harness.py
│   └── suites/                  # one file per eval layer
├── web/                         # React + TS + Tailwind
│   ├── src/pages/
│   ├── src/components/
│   └── src/api/
└── tests/
    ├── unit/
    ├── integration/
    └── security/
```

---

## 4. Stack and Conventions

| Concern | Choice |
|---|---|
| Language | Python 3.11+, TypeScript 5+ |
| API | FastAPI, async endpoints |
| Validation | Pydantic v2 everywhere; no untyped dicts crossing module boundaries |
| Orchestration | LangGraph state graph |
| DB | PostgreSQL 16 + pgvector |
| Cache/session | Redis |
| Frontend | React 18 + TypeScript + Tailwind + Vite |
| Tests | pytest + pytest-asyncio; vitest for frontend |
| Lint/format | ruff + black; eslint + prettier |
| Tracing | OpenTelemetry |

**Conventions:**
- Type hints on every function signature. `mypy` clean where practical.
- No hardcoded secrets, ever. Config via `pydantic-settings` reading env vars.
- No `print()`. Use structured logging with `case_id` in context.
- Every module gets a matching test file. A task is not done without tests.
- Prompts live in `llm/prompts/*.md`, never inline in Python. Each carries a version header.
- Async for all I/O. Connector and retrieval calls are awaitable.
- Commit convention: `<phase>-<task>: <summary>` e.g. `P2-T3: add hybrid search with ACL prefilter`.

---

## 5. Canonical Types — Do Not Redefine

Implement these in `core/models.py` and `core/enums.py` during Phase 0. All later code imports from here.

```python
# core/enums.py
class Intent(str, Enum):
    SALES_INQUIRY = "SALES_INQUIRY"
    BOOKING = "BOOKING"
    DOCUMENTATION = "DOCUMENTATION"
    PAYMENT = "PAYMENT"
    CONSTRUCTION_STATUS = "CONSTRUCTION_STATUS"
    MAINTENANCE = "MAINTENANCE"
    CONTRACTOR_UPDATE = "CONTRACTOR_UPDATE"
    COMPLAINT_ESCALATION = "COMPLAINT_ESCALATION"
    OTHER = "OTHER"

class Role(str, Enum):
    PUBLIC_LEAD = "public_lead"
    CUSTOMER = "customer"
    RESIDENT = "resident"
    BROKER = "broker"
    CONTRACTOR = "contractor"
    SALES_STAFF = "sales_staff"
    SITE_ENGINEER = "site_engineer"
    LEGAL_FINANCE = "legal_finance"
    MANAGER = "manager"

class RiskTier(int, Enum):
    AUTO = 0            # auto-send
    AUTO_NOTIFY = 1     # auto-send + notify owning team
    DRAFT_APPROVAL = 2  # human approves before send
    ESCALATE_ONLY = 3   # acknowledgement only, human owns

class Priority(str, Enum):
    P1 = "P1"; P2 = "P2"; P3 = "P3"; P4 = "P4"

class Channel(str, Enum):
    WEB_CHAT = "web_chat"; EMAIL = "email"; FORM = "form"
    CALL_TRANSCRIPT = "call_transcript"; INTERNAL_PORTAL = "internal_portal"
    CONTRACTOR_PORTAL = "contractor_portal"
```

```python
# core/models.py
class AccessScope(BaseModel):
    """Immutable. Passed to every retrieval and connector call."""
    actor_id: str
    role: Role
    booking_ids: list[str] = []
    unit_ids: list[str] = []
    project_ids: list[str] = []      # empty + manager/engineer role = all
    work_package_ids: list[str] = []
    model_config = ConfigDict(frozen=True)

class Citation(BaseModel):
    source_name: str
    source_id: str
    section: str | None = None
    effective_date: date | None = None
    is_stale: bool = False

class Classification(BaseModel):
    intent: Intent
    secondary_intent: Intent | None = None
    confidence: float                 # 0.0-1.0
    entities: dict[str, str] = {}     # project, tower, unit, customer_id, urgency
    sentiment: Literal["positive", "neutral", "negative"] = "neutral"

class AgentFinding(BaseModel):
    """Uniform return type for every specialist agent."""
    agent: str
    status: Literal["ok", "insufficient_data", "conflict", "error"]
    summary: str                       # prose, audience-neutral
    structured: dict[str, Any] = {}    # typed fields from connectors
    citations: list[Citation] = []
    confidence: float
    internal_only: bool = False        # true = must not reach a customer

class EscalationDecision(BaseModel):
    required: bool
    escalation_type: str | None = None
    owner_team: str | None = None
    sla_hours: int | None = None
    brief: str | None = None
    rationale: str

class ResponseDraft(BaseModel):
    mode: Literal["auto_send", "draft_for_approval", "acknowledgement_only", "refuse"]
    audience: Role
    text: str
    citations: list[Citation] = []
    next_action: str | None = None
```

```python
# orchestration/state.py
class CaseState(BaseModel):
    case_id: str
    channel: Channel
    scope: AccessScope
    raw_input: str
    masked_input: str
    classification: Classification | None = None
    findings: list[AgentFinding] = []
    risk_tier: RiskTier | None = None
    escalation: EscalationDecision | None = None
    response: ResponseDraft | None = None
    trace_ids: list[str] = []
    cost_tokens: int = 0
    error: str | None = None
```

```python
# connectors/protocol.py
class SystemConnector(Protocol):
    name: str
    async def health(self) -> dict: ...
    async def query(self, request: BaseModel, scope: AccessScope) -> BaseModel: ...
    async def write(self, action: BaseModel, scope: AccessScope,
                    approval: str | None = None) -> BaseModel: ...
```

Write operations at RiskTier 2+ must reject a `None` approval token **inside the connector**, not in the caller.

---

## 6. Agent Implementation Contract

Every specialist agent subclasses `BaseAgent` and satisfies:

```python
class BaseAgent(ABC):
    name: str
    prompt_version: str
    confidence_threshold: float = 0.7

    @abstractmethod
    async def run(self, state: CaseState) -> AgentFinding: ...
```

Rules for every agent:
- Never mutate `CaseState` directly. Return an `AgentFinding`; the graph merges it.
- Never call another agent. Coordination is the graph's job.
- Every factual claim in `summary` must map to a `Citation` or a `structured` field.
- On empty retrieval or connector failure, return `status="insufficient_data"` with `confidence=0.0`. Do not improvise.
- Set `internal_only=True` on any finding containing contractor disputes, cost data, safety-incident detail, or unapproved dates.

---

## 7. Definition of Done (applies to every task)

A task is complete only when all of these hold:
1. Code matches the file paths and type contracts in this document.
2. Unit tests written and passing; meaningful assertions, not smoke tests.
3. `ruff` and `black` clean (or `eslint`/`prettier` for frontend).
4. No secrets, no hardcoded absolute paths, no `print()`.
5. Docstring on every public function explaining *why*, not just *what*.
6. `README.md` updated if a new command or env var was introduced.
7. The task's own acceptance criteria in `BUILD_PLAN.md` are demonstrably met.
8. A short handoff note stating: what was built, what was assumed, what the next task will need.

---

## 8. When to Stop and Ask

Stop and report rather than proceeding if:
- A task requires changing a canonical type in Section 5.
- A task appears to require the model to produce a price, date, or ID not present in retrieved data.
- A task would place access-control logic inside a prompt.
- Seed data or corpus content needed for the task does not exist yet.
- Two tasks you have been given contradict each other.

Guessing at these creates silent correctness failures that are expensive to find later.
