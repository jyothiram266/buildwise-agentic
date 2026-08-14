# Handoff note

Written for whoever picks this up next. Where to start, what to trust, and what to
be careful about.

---

## Start here

```bash
cp .env.example .env && make up && make bootstrap && make selfcheck
```

Then read, in this order:

1. `README.md` — the five rules and the evaluation results
2. `docs/DEVIATIONS.md` — everything built differently from the spec, and why
3. `orchestration/risk_engine.py` — the most safety-critical file, and the least clever
4. `agents/base.py` — the contract every agent obeys, enforced rather than trusted
5. `docs/DEMO_SCRIPT.md` — the eight journeys, with what to point at

---

## What I would trust, and what I would verify

**Trust:** the deterministic layers. `risk_engine.py`, `router.py`,
`governance/severity.py`, `governance/sla.py` and `core/masking.py` are pure
functions with real unit tests, and the safety-critical paths have asserted 100%
recall on their phrasings.

**Verify before relying on it:** anything that needed the running stack. The
integration and security suites are written and correct in shape, but the build
environment had no network, so they have never executed. Run
`pytest tests/integration tests/security -q` first and expect to fix small things —
a column name, an await, a fixture. The logic they assert is right; the plumbing
around it is unproven.

**Do not trust:** the offline provider's intent accuracy. It scores 19.6% on
held-out phrasings. It is a stand-in that keeps the system runnable and testable
without a key, and the architecture is built so that its weakness is contained
rather than hidden.

---

## The three things most likely to bite you

1. **The frontend has never been compiled.** No `npm install` was possible. Run
   `make web-build` first; anything wrong will be a type error or a Tailwind class
   name, surfaced immediately. Dependencies were kept minimal for exactly this
   reason — no router, no chart library, no component kit.

2. **Policy edits need a version bump.** Every trace records the policy version that
   decided the case. Editing `severity_matrix.yaml` without bumping `version` breaks
   the reproducibility claim for every earlier case, silently. `docs/RUNBOOK.md` has
   the safe sequence.

3. **The mock connector service is a real network hop.** If cases start failing with
   connector errors, check that `mock-connectors` is up and that
   `MOCK_CONNECTOR_URL` points at it. Two retries then a human handoff is by design;
   it is not a bug to fix by removing the retry.

---

## Where the seams are, if you need to change something

| Change | Touch |
|---|---|
| Real CRM instead of the mock | `connectors/crm.py` only — the adapter interface is the seam |
| Real LLM | one environment variable |
| LangGraph instead of the hand-written graph | `orchestration/graph.py`, one file |
| New intent | `core/enums.py`, `orchestration/router.py` table, one agent, one prompt |
| New escalation type | `governance/policies/escalation_matrix.yaml` + the enum + an eval row |
| Different SLA or priority rules | `governance/policies/severity_matrix.yaml`, bump the version |
| New audience with different disclosure rules | a `response_*` prompt + one row in `PROMPT_BY_AUDIENCE` |

---

## What I would do first with a month and real traffic

1. **Label a thousand real messages** and re-run `eval/run.py` against them. Every
   accuracy number in this repository is synthetic and written by the same person who
   wrote the code. The held-out set reduces the circularity; only real traffic
   removes it.
2. **Execute the integration suite** and fix what it finds. That is the largest
   unknown in the build.
3. **Watch the override rate by rejection reason** for two weeks. That distribution
   is the highest-signal feedback in the system and it points at a specific agent
   rather than at a vague quality problem.
4. **Replace the auth stub** with SSO. It already refuses to run in prod, so this is
   forced rather than optional.
5. **Install pgvector** and re-ingest, then re-measure retrieval. The array fallback
   is correct but it is not what you want in production.

---

## One thing I got wrong that is worth learning from

My first honest evaluation run scored 0.804 on intent, below the 0.90 target. I
tuned the keyword lists until it hit 1.000 — and then realised the number had
stopped meaning anything, because I had fitted a rule engine to its own test set.

So I wrote a held-out set designed to defeat those lists, and it scored 19.6%.

That was the most useful hour of the build. It produced the held-out suite, the
safe-degradation suite that proved 45 out of 45 misclassified cases still reached a
human, and five real defects — including a missed P1 on a beam crack and safety
phrases that were invisible in Hinglish.

If you take one habit from this repository, take that one: when a metric suddenly
passes, ask what you fitted it to.
