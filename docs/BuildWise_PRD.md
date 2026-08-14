# Product Requirements Document (PRD)
## Agentic AI Real Estate & Construction Support System
**Client (Case Study):** BuildWise Realty & Construction Group
**Document version:** 1.0
**Status:** Draft for review
**Owner:** Capstone Team

---

## 1. Purpose of This Document

This PRD defines *what* the Agentic AI Support System must do, for whom, and how success will be judged. It is the contract between the capstone team and the reviewers. Technical design decisions live in the companion document, `BuildWise_System_Architecture.md`.

---

## 2. Problem Summary

BuildWise handles high-volume, multi-channel requests across the full property lifecycle — discovery, booking, documentation, construction tracking, possession, and post-sale maintenance. Today these flow through phone calls, email, WhatsApp, spreadsheets, and shared folders. Consequences:

- Response latency measured in hours or days for questions that have known answers.
- Inconsistent answers, because information lives in five places and no one place is authoritative.
- Duplicate work across sales, site, legal, finance, and support teams.
- No real-time management view of delayed milestones, open escalations, or at-risk leads.
- Revenue leakage from missed follow-ups and slow lead conversion.

**Root cause, stated plainly:** the company has the information but no reliable routing and retrieval layer over it.

---

## 3. Product Vision

> A single intelligent intake and coordination layer that receives any request from any channel, understands it, retrieves only approved information, drafts a grounded response or action, and escalates to the right human when the stakes require judgment.

**Design principle:** The system is an *assistive* layer, not a decision-maker. Anything involving money, legal commitment, safety, or a change to a customer's contractual position requires human approval by design, not by exception.

---

## 4. Goals and Non-Goals

### 4.1 Product Goals
| # | Goal | Measured By |
|---|------|-------------|
| G1 | Reduce time-to-first-response on customer inquiries | Median first-response latency |
| G2 | Give consistent, source-grounded answers | % of responses with citation to approved source |
| G3 | Route high-risk cases to the correct human team | Escalation precision & recall |
| G4 | Cut manual lookup effort for staff | Avg. lookups per resolved case (before/after) |
| G5 | Give leadership real-time operational visibility | Dashboard covering 6 core metrics |
| G6 | Maintain a complete audit trail | 100% of agent actions logged with rationale |

### 4.2 Explicit Non-Goals
- No execution of real financial transactions, refunds, or penalty waivers.
- No autonomous legal agreement generation or contract execution.
- No autonomous property allocation or price negotiation.
- No replacement of licensed legal, structural-engineering, safety, or financial professionals.
- No live production integration in the capstone scope (mock connectors only).

---

## 5. Users and Personas

| Persona | Role | Primary Needs | Access Level |
|---|---|---|---|
| **Priya** — Prospective Buyer | External | Unit availability, pricing, floor plans, location, possession timeline | Public / lead-tier data only |
| **Rakesh** — Existing Customer (booked) | External | Construction status, payment milestones, pending documents, possession date | Own booking record only |
| **Sunita** — Resident (post-possession) | External | Raise maintenance tickets, track resolution, warranty status | Own unit + community data |
| **Anil** — Broker / Channel Partner | External-Partner | Inventory availability, commission status, brochure assets | Partner-tier inventory data |
| **Deepak** — Sales Executive | Internal | Lead prioritisation, follow-up lists, quick answer lookup | CRM read, lead write |
| **Meera** — Site Engineer | Internal | Convert raw site notes into customer-ready summaries, flag delays | Project write, progress reports |
| **Faisal** — Contractor / Vendor | External-Partner | Report material shortages, submit progress, raise blockers | Own work-package scope |
| **Legal & Finance Officer** | Internal | Review flagged documentation and payment disputes | Full document + payment read |
| **Kavitha** — Project Manager / Leadership | Internal | Portfolio health, delayed milestones, escalation queue | Read-all + dashboards |

---

## 6. Scope

### 6.1 In Scope (Capstone Deliverable)
1. Multi-channel intake API (web chat, email-simulated, form, call-transcript paste, internal portal).
2. Eight specialised agents (Section 8) coordinated by an orchestrator.
3. RAG knowledge base over a seeded corpus: property FAQs, project status reports, documentation checklists, maintenance SLA policies, pricing sheets.
4. Mock system-of-record connectors: CRM, Project Management, Payments, Document Management, Ticketing.
5. Human-in-the-loop escalation workflow with a review queue.
6. Role-based access control and full audit logging.
7. Customer-facing chat UI + internal staff dashboard (functional prototype).
8. Evaluation harness: labelled test set for intent classification, groundedness, and escalation accuracy.

### 6.2 Out of Scope
- Live payment gateway, live CRM/ERP, live e-signature.
- Native mobile apps (responsive web only).
- Voice telephony integration (transcripts accepted as text input).
- Multilingual support beyond English (Hindi/Kannada noted as roadmap).
- IoT/drone site-capture ingestion (roadmap).

---

## 7. Functional Requirements

Requirements are written as `FR-<area>-<n>` and prioritised **P0** (must ship), **P1** (should ship), **P2** (roadmap).

### 7.1 Intake and Classification
| ID | Requirement | Priority |
|---|---|---|
| FR-INT-1 | Accept a request via REST endpoint with channel, raw text, optional attachments, and optional authenticated user identity. | P0 |
| FR-INT-2 | Normalise every request into a canonical `Case` object with a unique case ID. | P0 |
| FR-INT-3 | Classify each request into one of: `SALES_INQUIRY`, `BOOKING`, `DOCUMENTATION`, `PAYMENT`, `CONSTRUCTION_STATUS`, `MAINTENANCE`, `CONTRACTOR_UPDATE`, `COMPLAINT_ESCALATION`, `OTHER`. | P0 |
| FR-INT-4 | Extract entities: project name, tower/unit, customer ID, urgency, sentiment, requested action. | P0 |
| FR-INT-5 | Emit a confidence score per classification; route below-threshold cases to human triage rather than guessing. | P0 |
| FR-INT-6 | Deduplicate against open cases from the same customer within a 24-hour window and thread them. | P1 |

### 7.2 Property Information
| ID | Requirement | Priority |
|---|---|---|
| FR-PROP-1 | Retrieve unit availability filtered by project, configuration (1/2/3BHK, villa, commercial), budget range, and city. | P0 |
| FR-PROP-2 | Serve only *approved* pricing from the current published pricing sheet, with an effective-date stamp. | P0 |
| FR-PROP-3 | Never quote a discount, waiver, or negotiated rate; direct such requests to a sales executive. | P0 |
| FR-PROP-4 | Return floor plans, amenities, and possession timelines with source document references. | P0 |
| FR-PROP-5 | Include a staleness warning when the retrieved record is older than its configured freshness window. | P1 |

### 7.3 Construction Progress
| ID | Requirement | Priority |
|---|---|---|
| FR-CON-1 | Summarise milestone status per project/tower: completed, in-progress, pending, with % completion. | P0 |
| FR-CON-2 | Generate two summary registers from the same source data: an internal technical summary and a customer-safe summary. | P0 |
| FR-CON-3 | Suppress from customer-facing output: contractor disputes, internal cost data, unconfirmed delay speculation, safety-incident detail. | P0 |
| FR-CON-4 | Detect schedule slippage by comparing planned vs. actual milestone dates and flag projects exceeding a configurable threshold. | P0 |
| FR-CON-5 | Accept a free-text weekly site note from an engineer and return a structured, review-ready customer summary. | P0 |
| FR-CON-6 | Never state a revised possession date to a customer unless that date exists as an approved record. | P0 |

### 7.4 Documentation Support
| ID | Requirement | Priority |
|---|---|---|
| FR-DOC-1 | Return the stage-appropriate document checklist for a given customer's booking stage (KYC → booking → agreement → registration → loan → handover). | P0 |
| FR-DOC-2 | Compare submitted vs. required documents and list what is missing or expired. | P0 |
| FR-DOC-3 | Generate reminder drafts for pending documents; sending requires human or scheduled-policy approval. | P1 |
| FR-DOC-4 | Provide procedural guidance only — never interpret contract clauses or give legal advice. Route interpretation requests to Legal. | P0 |
| FR-DOC-5 | Redact/mask KYC identifiers (PAN, Aadhaar, bank account) in all logs, prompts, and model context. | P0 |

### 7.5 Maintenance Routing
| ID | Requirement | Priority |
|---|---|---|
| FR-MNT-1 | Classify post-possession requests into categories: plumbing, electrical, civil, lift, common-area, parking, water supply, security, warranty-claim. | P0 |
| FR-MNT-2 | Assign priority P1–P4 using an explicit severity matrix (safety and habitability first). | P0 |
| FR-MNT-3 | Auto-route to the mapped facility team and create a ticket in the mock ticketing system. | P0 |
| FR-MNT-4 | Immediately escalate safety-critical categories (gas leak, electrical hazard, structural crack, lift entrapment) to a human on-call path without waiting for normal routing. | P0 |
| FR-MNT-5 | Determine warranty coverage from the possession date and warranty policy, presenting it as an indication pending confirmation. | P1 |

### 7.6 Contractor Coordination
| ID | Requirement | Priority |
|---|---|---|
| FR-CTR-1 | Ingest contractor updates (progress, material status, manpower, blockers). | P0 |
| FR-CTR-2 | Correlate a reported blocker to the affected milestones and produce an impact statement. | P0 |
| FR-CTR-3 | Produce a daily blocker digest per project for the project manager. | P0 |
| FR-CTR-4 | Do not commit to contractors on payments, timelines, or scope changes. | P0 |

### 7.7 Escalation and Risk
| ID | Requirement | Priority |
|---|---|---|
| FR-ESC-1 | Detect and escalate: legal threat, regulatory complaint, payment dispute, refund demand, safety incident, media/social threat, repeated unresolved contact, severe negative sentiment. | P0 |
| FR-ESC-2 | Route each escalation type to a configured owner team with an SLA clock. | P0 |
| FR-ESC-3 | Produce an escalation brief: case history, what was attempted, risk rationale, recommended next action. | P0 |
| FR-ESC-4 | Escalate on low confidence, missing data, or conflicting sources — uncertainty is itself an escalation trigger. | P0 |
| FR-ESC-5 | Never close an escalated case autonomously. | P0 |

### 7.8 Response Generation
| ID | Requirement | Priority |
|---|---|---|
| FR-RES-1 | Generate responses grounded strictly in retrieved context; refuse and escalate when context is insufficient. | P0 |
| FR-RES-2 | Attach source references (document name, section, effective date) to every factual claim. | P0 |
| FR-RES-3 | Adapt tone and disclosure level by audience: customer, broker, contractor, internal. | P0 |
| FR-RES-4 | Route responses above a risk threshold to a draft-for-approval state instead of auto-send. | P0 |
| FR-RES-5 | Include a next-action recommendation and, where relevant, an expected timeline drawn from policy. | P1 |

### 7.9 Governance, Dashboard, Audit
| ID | Requirement | Priority |
|---|---|---|
| FR-GOV-1 | Enforce role-based access control at the retrieval layer, so a user cannot receive data outside their scope even via prompt manipulation. | P0 |
| FR-GOV-2 | Log every agent invocation: inputs, retrieved sources, model output, confidence, decision, actor, timestamp. | P0 |
| FR-GOV-3 | Provide a human review queue with approve / edit / reject / reassign actions. | P0 |
| FR-GOV-4 | Dashboard shows: open cases by type, median response time, escalation queue and ageing, delayed milestones, unresolved maintenance tickets by SLA breach, leads needing follow-up today. | P0 |
| FR-GOV-5 | Support prompt/policy versioning so any past response can be reproduced with the config that produced it. | P1 |

---

## 8. Agent Specifications

Each agent is defined by a narrow contract. Narrow contracts are what make the system auditable.

| Agent | Input | Output | Tools / Sources | Autonomy |
|---|---|---|---|---|
| **Inquiry Classification** | Raw request + channel + identity | Intent, entities, urgency, confidence, routing plan | Classification model, entity extractor | Full (routing only) |
| **Property Information** | Structured property query | Availability set, pricing, plans, timeline + citations | Inventory API, pricing sheet, brochure KB | Full for read-only approved data |
| **Construction Progress** | Project/tower ID or raw site note | Milestone summary (internal + customer variant), slippage flags | Project mgmt API, site reports KB | Draft-only for customer-facing output |
| **Documentation Support** | Customer ID + stage | Required vs. submitted checklist, gaps, next steps | DMS API, checklist KB | Full for checklists; draft for reminders |
| **Maintenance Routing** | Complaint text + unit ID | Category, priority, assigned team, ticket ID | Ticketing API, SLA policy, severity matrix | Full below P1; P1 co-notifies human |
| **Contractor Coordination** | Vendor update | Blocker record, milestone impact, PM digest | Project mgmt API, procurement KB | Full for internal reporting only |
| **Escalation & Risk** | Case + full conversation history | Risk classification, owner team, escalation brief | Risk taxonomy, routing matrix | Full to *raise*; never to resolve |
| **Response Generation** | Agent findings + audience + case | Final or draft response with citations | Response templates, tone policy | Governed by risk tier (Section 9) |

---

## 9. Autonomy and Approval Policy

This table is the safety spine of the product.

| Risk Tier | Examples | System Behaviour |
|---|---|---|
| **Tier 0 — Auto-respond** | Amenities, published pricing, generic document checklists, project location, standard maintenance ticket creation | Auto-send + log |
| **Tier 1 — Auto-respond with notice** | Milestone status, availability of units, warranty indication | Auto-send + notify owning team |
| **Tier 2 — Draft for approval** | Possession-date change explanation, customer-facing construction delay note, payment-milestone clarification, contractor commitment | Human approves before send |
| **Tier 3 — Escalate, no auto-response** | Refund demand, legal notice, payment dispute, safety incident, structural defect, discount/waiver request | Acknowledgement only + immediate human ownership |

Default on ambiguity is the **higher** tier.

---

## 10. Key User Journeys (Acceptance Criteria Format)

**UJ-1 — Prospective buyer, 2BHK within budget**
*Given* Priya asks for 2BHK units under ₹85L in Whitefield, *when* the system processes it, *then* it returns matching available units with current approved pricing, floor-plan links, possession timeline, and a source stamp; creates a lead in mock CRM; and offers a site-visit next action. Unavailable configurations are stated as unavailable rather than substituted silently.

**UJ-2 — Existing customer, Tower B status**
*Given* authenticated customer Rakesh asks for Tower B status, *when* processed, *then* the customer-safe summary is returned with milestone completion %, last-updated date, and next milestone — with no internal contractor or cost detail. If the latest report is older than the freshness window, the response says so.

**UJ-3 — Pending documents for registration**
*Given* Rakesh asks what is pending for agreement registration, *when* processed, *then* the system returns required vs. submitted, names each gap, states where to submit, and offers a reminder draft. No clause interpretation is offered.

**UJ-4 — Possession date changed, customer wants escalation**
*Given* Rakesh disputes a changed possession date, *when* processed, *then* the Escalation Agent classifies it as Tier 3, sends only an acknowledgement with a response SLA, generates an escalation brief for the project + customer-relations owner, and starts the SLA clock. No new date is asserted.

**UJ-5 — Site engineer weekly note → customer summary**
*Given* Meera submits a raw progress note, *when* processed, *then* the system returns a structured internal summary and a separate customer-ready draft, flags any slippage, and places the customer draft in the approval queue (Tier 2).

**UJ-6 — Contractor reports material shortage**
*Given* Faisal reports a cement shortage, *when* processed, *then* the system logs the blocker, identifies affected milestones, produces an impact statement with a delay estimate range, notifies the PM, and makes no commitment to the contractor.

**UJ-7 — Post-possession plumbing issue**
*Given* Sunita reports a bathroom leak, *when* processed, *then* the system categorises it as plumbing, assigns priority per the severity matrix, creates a ticket, routes to the facility team, and returns the ticket ID with the SLA window.

**UJ-8 — Sales manager daily priority list**
*Given* Deepak's manager requests today's high-priority follow-ups, *when* processed, *then* the system returns a ranked list with reason codes (ageing, high intent, site-visit done, payment pending) and last-contact dates.

---

## 11. Non-Functional Requirements

| Category | Requirement |
|---|---|
| **Latency** | P95 ≤ 5s for retrieval-only responses; ≤ 15s for multi-agent workflows; streaming for perceived responsiveness |
| **Availability** | 99% for the prototype; graceful degradation to human-queue if any agent or connector fails |
| **Scalability** | Design target 5,000 requests/day, 200 concurrent sessions |
| **Groundedness** | ≥ 95% of factual claims traceable to a retrieved source; zero tolerance for fabricated prices, dates, or unit numbers |
| **Security** | RBAC at retrieval layer; PII masking; encryption in transit and at rest; prompt-injection defences on all ingested documents and user text |
| **Privacy** | Customer data scoped to the authenticated identity; no cross-customer leakage; retention policy defined |
| **Auditability** | Full immutable trace per case, replayable with the prompt/policy version used |
| **Observability** | Per-agent latency, token cost, confidence distribution, escalation rate, approval override rate |
| **Cost** | Tracked per case; small models used for classification, large models reserved for synthesis |
| **Accessibility** | WCAG 2.1 AA on customer-facing UI |

---

## 12. Success Criteria

| Metric | Target |
|---|---|
| Intent classification accuracy (9-class, labelled test set) | ≥ 90% |
| Entity extraction F1 (project, unit, customer, urgency) | ≥ 85% |
| Groundedness / citation-supported claims | ≥ 95% |
| Hallucinated price, date, or unit number | 0 in the evaluation set |
| Escalation recall on high-risk cases | ≥ 95% (recall prioritised over precision) |
| Escalation precision | ≥ 80% |
| Maintenance routing accuracy | ≥ 90% |
| Human approval override rate on Tier 2 drafts | ≤ 25% |
| Median first-response latency | < 30s vs. current baseline in hours |
| Manual lookups per resolved case | ≥ 50% reduction (demonstrated) |
| Audit completeness | 100% of actions logged |

**Note on the recall/precision asymmetry:** a missed escalation is a legal or safety failure; a false escalation is a few minutes of a human's time. The thresholds reflect that asymmetry deliberately.

---

## 13. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Hallucinated pricing or possession dates | Legal exposure, loss of trust | Strict retrieval-grounded generation; numeric claims must match a retrieved field; refuse-and-escalate on gaps |
| Prompt injection via uploaded site reports or customer text | Data leakage, unauthorised action | Treat all ingested content as untrusted; enforce RBAC below the model; no tool execution from document-derived instructions |
| Over-automation of sensitive cases | Regulatory and reputational harm | Risk-tier policy (Section 9); default to higher tier |
| Stale source data | Wrong answers delivered confidently | Freshness windows per source; staleness disclosure in output |
| Knowledge-base gaps | Unhelpful refusals | Gap logging feeds a KB backlog; refusal is preferred to invention |
| Staff distrust / non-adoption | Prototype unused | Show sources and confidence in the UI; keep humans in control of sends |
| Cost escalation from large-model use | Unsustainable unit economics | Tiered model routing; caching; per-case cost telemetry |
| Mock-to-real integration gap | Rework post-capstone | Connector interface abstraction from day one |

---

## 14. Assumptions and Dependencies

**Assumptions:** synthetic but realistic datasets are acceptable for the capstone; approved knowledge sources can be represented as static documents; a single organisation tenant; English-only interaction; identity is provided by a mock auth layer.

**Dependencies:** LLM API access; vector store; the five mock connectors; a labelled evaluation set (~200–300 examples) authored by the team.

---

## 15. Delivery Plan

| Phase | Weeks | Output |
|---|---|---|
| **1 — Foundation** | 1–2 | Finalised PRD + architecture; datasets and KB seeded; connector interfaces stubbed; eval set drafted |
| **2 — Core Agents** | 3–4 | Classification, Property, Documentation agents; RAG pipeline; orchestrator skeleton |
| **3 — Workflow Agents** | 5–6 | Construction, Maintenance, Contractor, Escalation agents; risk-tier policy engine |
| **4 — Experience Layer** | 7–8 | Customer chat UI; staff dashboard; approval queue; audit viewer |
| **5 — Evaluation & Hardening** | 9–10 | Eval harness run; accuracy tuning; injection and RBAC testing; cost telemetry |
| **6 — Demo & Handover** | 11–12 | End-to-end demo of all 8 use cases; final presentation; roadmap document |

---

## 16. Roadmap Beyond Capstone

- Multilingual support (Hindi, Kannada, Tamil) with language-matched escalation routing.
- Voice channel integration with live call transcription.
- Predictive delay modelling from historical milestone and vendor performance data.
- Drone / site-photo ingestion for automated progress verification.
- Broker self-service portal with live inventory holds.
- Proactive outbound updates instead of reactive answers.
- Multi-tenant deployment for other developers as a productised offering.

---

## 17. Open Questions for Reviewer Sign-off

1. Is the 9-class intent taxonomy sufficient, or should `BOOKING` split into pre- and post-agreement?
2. Should broker-tier users see live inventory counts, or only availability status?
3. What is the approved SLA per escalation type — needed to set the dashboard clocks?
4. Who owns approval for Tier 2 construction drafts: Site Engineer, Project Manager, or Customer Relations?
5. Is a maintenance ticket created automatically for P1 safety cases, or does the human on-call path create it?

---

*Companion document: `BuildWise_System_Architecture.md`*
