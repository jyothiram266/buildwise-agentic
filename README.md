# BuildWise — agentic support for real estate and construction

A multi-agent support system for a residential developer. It answers customers,
prospects, brokers, contractors and internal staff across sales, documentation,
payments, construction status and maintenance — and it is built so that the
interesting question is not "can it answer" but "can you trust the answer".

Five rules shape every file in this repository:

1. **Numbers come from systems of record; prose comes from approved documents.**
   If a figure is not in a connector response, the system says it does not have it.
   It never estimates.
2. **Authorisation sits below the model.** Every retrieval and every connector call
   carries an `AccessScope`, and the filtering happens in SQL predicates. No prompt
   is ever asked to keep a secret.
3. **Policy is deterministic code.** Routing, risk tiering, priority, SLA and RBAC
   are pure functions over policy files. Models handle language only.
4. **Uncertainty is an output.** Every agent returns a confidence. Below threshold,
   the case goes to a person.
5. **The payments connector is read-only.** No code path can write a payment,
   refund, waiver or discount. The write method exists only to refuse.

---

## Quickstart

Requires Docker and Docker Compose. No API key needed.

```bash
git clone <this repo> && cd buildwise-agentic
cp .env.example .env

make up          # postgres, redis, mock systems of record, api, web
make bootstrap   # migrate, seed, build the corpus, ingest  (~60s)
make selfcheck   # confirms the demo is ready and tells you what to fix if not
```

Open **http://localhost:3000**. Use the "Acting as" selector to switch identity —
that is the demo. Ask the same question as a customer and then as a manager and
watch what changes.

API docs are at http://localhost:8000/docs.

<details>
<summary>Running without Docker</summary>

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Postgres and Redis must be reachable; see .env for the URLs
python scripts/bootstrap.py
uvicorn connectors.mock_server.main:app --port 8100 &
uvicorn api.main:app --port 8000 --reload &
cd web && npm install && npm run dev
```
</details>

Full deployment instructions, including hosting on Render or a single VM, are in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

---

## What it does, by journey

| Journey | Behaviour worth noticing |
|---|---|
| Prospect asks for a 2BHK under ₹85L in Whitefield | Cites the price list with its effective date; creates a lead |
| Prospect asks for a 1BHK at a project that has none | Says so and offers **nothing** in its place. Silent substitution is a fabrication about what was asked |
| Customer asks for tower status | Customer-safe wording; an unapproved revised possession date is never in the payload it reads |
| Customer asks what documents are pending | Distinguishes **missing** from **expired** — an expired sanction letter is a gap, not a submission |
| Customer disputes a possession date and mentions a refund | Tier 3: acknowledgement only, escalation brief, SLA clock started. No date, no amount, no liability |
| Engineer files a messy site note | Two outputs from one note: internal technical summary and a customer-safe version, both queued for approval |
| Contractor reports a cement shortage and asks about payment | Delay as a **range with assumptions**, never a date. Zero statements about payment |
| Resident reports a leak | Category, deterministic priority, ticket, SLA. Gas smell or entrapment forces P1 and pages on-call |
| Sales user asks who to follow up with | Ranked list where every position carries reason codes, so the ranking is checkable |

---

## Architecture

```
   channels (chat · email · whatsapp · console)
        │
   ┌────▼─────────────────────────────────────────────┐
   │ intake → mask PII → classify → route             │  orchestration/graph.py
   │   → specialists (concurrent) → risk → escalate?  │  explicit async state machine
   │   → respond → disclosure gate → persist          │
   └────┬─────────────────────────────────────────────┘
        │
   ┌────▼──────────┐  ┌──────────────┐  ┌─────────────────┐
   │ 10 agents     │  │ deterministic│  │ governance      │
   │ language only │  │ policy       │  │ rbac · audit    │
   │               │  │ risk · router│  │ sla · review    │
   └────┬──────────┘  └──────────────┘  └─────────────────┘
        │
   ┌────▼───────────────┐   ┌────────────────────────────┐
   │ retrieval          │   │ connectors (HTTP :8100)    │
   │ hybrid + ACL in SQL│   │ crm · pm · payments(RO)    │
   │ rerank · freshness │   │ dms · ticketing            │
   └────────────────────┘   └────────────────────────────┘
                    │                    │
                    └──── Postgres ──────┘
```

The systems of record run as a **separate process on a separate port**, so the
network boundary is real: adapters exercise timeouts, retries and serialisation
rather than calling functions that happen to be in the same interpreter. Replacing
the mock CRM with a real one means pointing an adapter somewhere else.

### Risk tiers

| Tier | Meaning | Example |
|---|---|---|
| 0 | Answer automatically | Availability, published price, document checklist |
| 1 | Answer, notify the owning team | Payment position for a customer |
| 2 | Draft, a human approves before sending | Anything internal heading for an external audience; confidence below 0.70 |
| 3 | Acknowledge only, a human owns it | Refund, legal notice, safety incident, possession dispute, discount request |

Tiering is a pure function in `orchestration/risk_engine.py` — six ordered rules,
zero model calls, and ambiguity always resolves upward.

---

## Evaluation results, reported honestly

Run `make eval`. The harness labels every number with the provider that produced
it, because the default provider is not a model.

**With the deterministic offline provider (`LLM_PROVIDER=mock`, the default):**

| Suite | Metric | Result | Target |
|---|---|---|---|
| maintenance | category accuracy | **1.000** | ≥0.90 |
| maintenance | priority accuracy | **1.000** | — |
| maintenance | **safety-critical recall** | **12/12** | 100% |
| escalation | recall | **1.000** | ≥0.95 |
| escalation | precision | **1.000** | ≥0.80 |
| injection | detection recall | **1.000** | 1.00 |
| intent | accuracy (fitted set) | 0.988 | ≥0.90 |
| **intent_holdout** | **accuracy on unseen phrasing** | **0.214** | — |
| **safe_degradation** | **misclassified cases still routed to a human** | **44/44 = 1.000** | ≥0.95 |

Read those last three rows together, because they are the most important result in
this repository.

The **1.000 on `intent` is not an achievement.** The default provider is a
rule-based keyword scorer, and I tuned its keyword lists until that suite passed.
Fitting a rule engine to its own test set is trivial and proves nothing. So the
harness includes `intents_holdout.jsonl` — 56 messages written to defeat those
keyword lists, using the indirect, colloquial, code-switched English that real
customers send ("do i still owe you anything", "the wall is going dark near the
window", "boss, 30 bags left only, tomorrow we sit idle").

On that set the scorer gets **21.4%**. That is the real capability of the thing
sitting in the model's slot, and it is exactly why a real model belongs there.

**And here is the part that matters:** of the 44 held-out messages the classifier
got wrong, **44 were still routed to a human** — most because confidence fell below
the 0.70 threshold, the rest because the risk engine matched a tier-3 trigger phrase
against the raw text independently of the intent. Zero were answered automatically
with a confident wrong answer.

That is the architecture doing its job. Deterministic tiering does not trust the
classifier, so bad classification degrades into a handoff rather than into a
confident mistake. The safety story does not depend on model quality — which is a
claim you can only make if you have measured it with a deliberately bad model in
the slot.

To measure a real model:

```bash
LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-... make eval
```

### What running the tests found and fixed

The suites above are static checks and unit tests. Executing the integration and
security suites against a live stack found seven more defects that no amount of
static analysis would have surfaced:

- **The hazard path was gated behind classification confidence.** "I can smell gas
  near the kitchen pipe" classified at 0.35, fell into triage, and the maintenance
  agent — which holds the severity rules — never ran. No ticket, no P1, no on-call
  page. The severity matrix scored 12/12 on that exact phrasing *in isolation*, so
  the unit tests were green while the end-to-end path was unsafe. Hazard detection
  now runs on the raw text in both the router and the risk engine, before any
  confidence gate, and the same applies to contractor identity and sales follow-up
  phrasing.
- **Every response failed with `AttributeError`.** Per-run accounting was initialised
  in `BaseAgent.run()`, but two agents are entered through their own methods, so the
  first `generate()` call raised. The graph caught it and turned it into a pipeline
  failure — the symptom was "no response produced", eleven tests deep.
- **A false "nothing is pending".** The checklist parser expected bullet lines; the
  corpus renders tables. It silently fell back to "whatever the DMS holds", which can
  only report documents that exist and never a missing one — so a customer with two
  pending items and one expired was told they were complete. The corpus now carries a
  machine-readable `Type` column, and an unparsed checklist raises instead of
  reporting completeness.
- **"registration" is not a stage name.** The records say `registered`, so the query
  returned nothing. Stage aliases are now explicit, and a question about a future
  stage is clamped back to the stage actually in progress.
- **Nearest-neighbour search has no notion of "irrelevant".** A nonsense query
  returned twenty confident-looking chunks, so the knowledge-gap path never fired and
  the agent had irrelevant context to ground an answer in. Dense retrieval now has a
  relevance floor, calibrated against 15 real and 7 nonsense queries and declared per
  embedding provider, because the threshold is a property of the embedding space
  rather than of the corpus.
- **An engineer's site note was routed to the contractor agent.** The vocabulary is
  identical to a vendor update; only the caller's identity distinguishes them, and
  FR-CON-5 requires the construction agent so both summaries get produced.
- **Silent JSONB double-encoding.** Every pooled connection registers a JSON codec,
  and four call sites also called `json.dumps`, so `agent_trace.output` and
  `cases.findings` stored quoted strings and read back as `str`. Nothing raised; the
  audit trail was simply wrong when anyone looked at it.
- **One pool for many event loops.** An asyncpg pool is bound to its creating loop;
  a single module-level pool broke 37 tests and would break any multi-loop process.
- **Injection recall was 0.30, not the 1.00 I first reported.** The pattern list only
  covered "ignore previous instructions" phrasing and missed uppercase variants,
  "prior", chat-template markers, and role-prefix spoofing. My own measurement of
  that metric was wrong; the test suite corrected it. Now 15/15 with zero false
  positives on a benign set that includes deliberate traps.

Two of my assertions were also wrong rather than the code: pricing sheets are
customer-facing by design (FR-PROP-2), and `SearchDiagnostics` field names differed.

### What the offline evaluation found and fixed

These were real defects, caught by the suites rather than by review:

- **A missed P1 on a beam crack.** "A crack has appeared across the beam" matched
  no hazard phrase. Fixed by adding co-occurrence pairs (`crack` + `beam`) to the
  severity matrix, since phrase lists cannot cover every word order.
- **A missed P1 on lift entrapment.** "The lift stopped between floors with someone
  inside" matched nothing. Entrapment now has the widest phrase list of any hazard
  class — a miss there is a person in a metal box.
- **Substring collisions.** "S*parking*" classified as a parking issue and "tiles
  have *lift*ed" as a lift issue. All signal matching is now word-boundary aware,
  with an explicit `*` suffix for intentional prefixes.
- **Hinglish hazards invisible.** "Gas ka smell aa raha hai" and "current lag raha
  hai" both scored zero. A hazard list that only reads formal English under-serves
  exactly the residents most likely to be reporting a real emergency.
- **Overconfident calibration.** The scorer saturated at 0.96, which silently
  disabled the below-threshold escalation path. The ceiling is now 0.88, and
  `suite_calibration` asserts that confidence still separates right from wrong.

---

## Requirement coverage

`make audit` walks every requirement in the PRD, finds the code that implements it
and the test that proves it, and fails if either is missing:

```
All 46 requirements, 5 design rules and 8 journeys are implemented.
```

The audit is a script rather than a checklist in a document, because a checklist
goes stale the first time someone deletes a function.

---

## Layout

```
core/           frozen contract types, enums, PII masking, typed errors
orchestration/  graph (async state machine), risk engine, router, state
agents/         10 agents; base.py enforces the contract mechanically
connectors/     5 adapters + the mock systems of record (separate service)
retrieval/      chunking, embeddings, hybrid search with ACL in SQL, rerank
governance/     rbac, audit + replay, sla, review queue, severity, registry
llm/            provider-agnostic client, 13 versioned prompts, offline provider
db/             schema, migrations, deterministic seed generator
api/            FastAPI app, routes, DI, schemas
web/            React + Vite + Tailwind console
eval/           harness, dataset generators, held-out set
tests/          unit (no deps) · integration · security
docs/           deployment, runbook, demo script, deviations
```

---

## Things I would change before production

Stated plainly because a prototype that hides its edges is harder to build on:

- **The offline provider is a rule engine.** It exists so the system runs with no
  API key and so tests are deterministic. It is not a model, and the held-out score
  says so. Production sets `LLM_PROVIDER=anthropic`.
- **The graph is hand-written, not LangGraph.** Same node/edge/checkpoint
  semantics, contained in `orchestration/graph.py`. I could not verify against
  LangGraph's live API in a network-isolated build, and shipping unverified code
  against a fast-moving dependency is worse than a small executor I can reason
  about. Swapping it is one file.
- **No SQLAlchemy.** Raw asyncpg, so every ACL predicate is a WHERE clause a
  reviewer can read at a glance. An ORM would hide the thing most worth seeing.
- **The eval sets are synthetic.** Written by the same person who wrote the code,
  which the held-out set mitigates but does not remove. The fix is labelled
  production traffic; there is no substitute.
- **`/api/auth/token` is a demo stub** that mints a token for any actor in the
  directory. It refuses to run when `APP_ENV=prod`. Replace with SSO.
- **Redis is optional.** Connector caching degrades to no caching, logged rather
  than silent.

---

## Commands

```bash
make audit       # map all 46 PRD requirements to code and tests
make up          # start the stack
make bootstrap   # migrate + seed + corpus + ingest (idempotent)
make selfcheck   # is the demo ready, and if not, what fixes it
make test        # unit, integration, security
make eval        # evaluation report against PRD targets
make lint        # ruff + black
make logs        # follow the API
make down        # stop; add -v to drop volumes
```
