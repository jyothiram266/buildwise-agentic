---
source_id: POL-ESC-ROUTE
source_name: Escalation Routing Matrix
collection: policies
effective_date: 2026-02-01
freshness_days: 365
audience_scope: [public_lead, customer, resident, broker, contractor, sales_staff, site_engineer, legal_finance, manager]
---

# Escalation Routing Matrix

**Policy:** POL-ESC-ROUTE · version 1.2.0 · effective 2026-02-01

## Routing table

| Escalation type | Owner team | Response SLA | Minimum tier |
|---|---|---|---|
| Refund or cancellation demand | legal_finance | 24 h | Tier 3 |
| Legal notice or threat of legal action | legal_finance | 8 h | Tier 3 |
| Payment or demand-note dispute | legal_finance | 24 h | Tier 3 |
| Safety incident or injury risk | safety_ehs | 2 h | Tier 3 |
| Suspected structural defect | structural_engineering | 8 h | Tier 3 |
| Discount, waiver or negotiated rate request | sales_leadership | 24 h | Tier 3 |
| Regulatory or authority complaint | legal_finance | 8 h | Tier 3 |
| Media or social-media escalation threat | corporate_communications | 4 h | Tier 3 |
| Possession-date change dispute | customer_relations | 24 h | Tier 3 |
| Repeated unresolved contact | customer_relations | 12 h | Tier 2 |
| Contractor seeking a payment, timeline or scope commitment | procurement | 24 h | Tier 2 |
| Pipeline confidence below threshold | customer_relations | 12 h | Tier 2 |
| Conflicting approved sources | knowledge_ops | 12 h | Tier 2 |
| Required system-of-record data unavailable | customer_relations | 12 h | Tier 2 |

## Rules

1. Where more than one type matches, the shortest SLA and the highest tier apply.
2. Tier 3 means no substantive automated answer is sent. The customer receives an
   acknowledgement, a named owning team and a response commitment.
3. Uncertainty is itself a trigger. Low pipeline confidence, conflicting approved
   sources and missing system-of-record data each raise an escalation on their
   own, independent of the topic.
4. No automated path resolves or closes an escalation. Closure is a human action
   recorded against a named person.
5. The SLA clock starts when the escalation record is created, not when a human
   opens it.
