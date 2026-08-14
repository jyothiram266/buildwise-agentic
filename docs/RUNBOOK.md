# Runbook

Operating notes for whoever is on call. Organised by the symptom you would actually
see, not by component.

---

## Health and first response

```bash
curl -s localhost:8000/health | jq            # API + database
curl -s localhost:8000/api/health/connectors  # the five systems of record
python scripts/selfcheck.py                   # everything, with fixes
```

`/health` reports `dense_mode`. `array` means pgvector is absent and cosine is
running in Python — correct behaviour, slower ranking, ACL unaffected.

---

## "The system is answering everything with 'I don't have that'"

Almost always empty retrieval. Check:

```sql
SELECT count(*) FROM chunks;
SELECT collection, count(*) FROM documents_corpus GROUP BY 1;
```

If chunks is zero: `make ingest`. If the corpus is empty:
`python scripts/build_corpus.py` then `make ingest`.

If both are populated, look at the KB gap log — that is the content team's queue and
it distinguishes "we have no document about this" from "retrieval is broken":

```bash
curl -s localhost:8000/api/audit/gaps/kb -H "X-Actor-Id: STF-MGR-01" | jq
```

---

## "Everything is going to the approval queue"

Expected if confidence is low across the board. Check the distribution:

```sql
SELECT round(confidence,1) AS band, count(*) FROM cases
WHERE created_at > now() - interval '1 day' GROUP BY 1 ORDER BY 1;
```

If most cases sit below 0.70, the classifier is struggling. With
`LLM_PROVIDER=mock` that is the documented behaviour on unfamiliar phrasing — the
held-out accuracy is 19.6% and the system is correctly declining to act on it.
Switch to a real provider.

Do **not** raise the thresholds to clear the queue. That converts a visible backlog
into invisible wrong answers. If they must move, move them for one intent at a time
and watch the override rate.

---

## "A tier-3 case did not escalate"

The risk engine is a pure function, so this is reproducible offline:

```python
from orchestration import risk_engine
from core.enums import Role
print(risk_engine.match_triggers("<the exact message text>"))
```

Empty result means no trigger phrase matched. Fix the phrase list in
`governance/policies/escalation_matrix.yaml`, **bump the version**, and add the
phrasing to `eval/datasets/escalation.jsonl` so it stays fixed.

The version bump matters: every trace records the policy version that decided it,
and editing a policy without bumping invalidates the audit trail for every earlier
case.

---

## "A safety-critical complaint was not P1"

Same shape, higher stakes:

```python
from governance.severity import detect_safety_critical
print(detect_safety_critical("<the exact message text>"))
```

Add the phrasing to `severity_matrix.yaml` under the right hazard class. Prefer a
`co_occurrence` pair over a long phrase when word order varies — that is how
"a crack has appeared across the beam" was fixed. Then add it to
`tests/unit/test_severity.py`, which asserts 100% recall.

Hinglish and code-switched phrasings belong in these lists as first-class entries,
not as an afterthought. See the `gas_leak` class for the pattern.

---

## "A customer saw something they should not have"

Treat as an incident.

1. **Capture the case** — `GET /api/audit/{case_id}` as a manager. Note which
   sources were retrieved and which agent produced the finding.
2. **Establish which layer failed.** There are four, and the answer changes:
   - the connector should have stripped it (mock server scope predicates)
   - retrieval should have filtered it (`audience_scope` in SQL)
   - the finding should have been marked `internal_only`
   - the disclosure gate should have caught it in the generated text
3. **Reproduce in a test** in `tests/security/test_acl.py` before changing anything.
4. **Fix the lowest layer that failed**, not the highest. Patching the gate when the
   connector leaked leaves the data available to every future code path.

The unapproved-possession-date case has two independent layers by design — the
connector strips it for external roles *and* the gate checks the text. Both failing
at once should be very unlikely, and if it happens, that is the finding.

---

## "Latency is above the 15 second target"

```sql
SELECT intent, avg(latency_ms)::int, percentile_disc(0.95)
  WITHIN GROUP (ORDER BY latency_ms) AS p95, count(*)
FROM cases WHERE created_at > now() - interval '1 hour'
GROUP BY 1 ORDER BY 3 DESC;
```

Then narrow it with the per-step timings, which every trace row carries:

```sql
SELECT agent, avg(latency_ms)::int, max(latency_ms), count(*)
FROM agent_trace WHERE ts > now() - interval '1 hour'
GROUP BY 1 ORDER BY 2 DESC;
```

Usual causes, in order: a slow connector (check retries in the logs), retrieval in
array mode over a grown corpus (install pgvector), or specialists running in series
because the router returned them in a way that defeated the concurrent gather.

---

## "Cost per case is climbing"

```bash
curl -s "localhost:8000/api/dashboard?window_days=7" -H "X-Actor-Id: STF-MGR-01" \
  | jq '.cost'
```

The per-intent breakdown usually points at one prompt. `COST_ALERT_USD_PER_CASE`
logs a warning per case above threshold; grep for `case_cost_above_alert`.

Cheapest lever: check that agents which do not need a large model are not using
one. Each prompt declares its `model_tier` in frontmatter.

---

## Changing a policy safely

1. Edit the YAML in `governance/policies/`.
2. **Bump `version`.** Non-negotiable — traces reference it.
3. Add the case that motivated the change to the matching eval dataset.
4. `make eval` — confirm nothing regressed, especially safety recall.
5. `python scripts/build_corpus.py && make ingest` if the policy is published as a
   document, so the customer-facing text matches the code.
6. Deploy. The registry validates at boot; a malformed policy fails the deploy
   rather than the first request that touches it.

---

## Changing a prompt safely

1. Copy the file to a new version: `classification_v1.md` → `classification_v2.md`.
2. Edit the new one and set `version: v2` in the frontmatter.
3. The registry resolves the highest version automatically. The old file stays so
   historical traces remain reproducible — **do not delete it.**
4. `make eval` before and after, and compare.

---

## Backup and restore

```bash
docker compose exec postgres pg_dump -U buildwise buildwise | gzip > backup.sql.gz
gunzip -c backup.sql.gz | docker compose exec -T postgres psql -U buildwise buildwise
```

`agent_trace` has an append-only trigger, which means a naive restore into a
non-empty database will fail on conflict rather than overwrite. That is intended.
Restore into a fresh database.

---

## Things that are supposed to fail

Worth knowing so you do not "fix" them:

| Behaviour | Why |
|---|---|
| `POST /payments/write` returns 405 | Design rule #5. The route exists only to make the refusal visible over the wire |
| A tier-2 write without an approval token raises | The connector validates approval itself; the caller is not trusted |
| An out-of-scope read returns empty, not 403 | A distinguishable error confirms the record exists |
| `X-Actor-Id` stops working in prod | It is a dev convenience; prod must wire real auth |
| `UPDATE agent_trace` raises | Append-only, enforced by trigger rather than convention |
| Unknown prompt id raises at startup | Better than discovering it on a customer's case |
| A second decision on a review item is refused | One human decision per item, recorded once |
