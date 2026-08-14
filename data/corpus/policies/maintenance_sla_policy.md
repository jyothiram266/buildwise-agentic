---
source_id: POL-MNT-SEV
source_name: Maintenance SLA and Severity Matrix
collection: policies
effective_date: 2026-04-01
freshness_days: 365
audience_scope: [public_lead, customer, resident, broker, contractor, sales_staff, site_engineer, legal_finance, manager]
---

# Maintenance SLA and Severity Matrix

**Policy:** POL-MNT-SEV · version 1.5.0 · effective 2026-04-01

## Service levels

| Priority | First response | Resolution SLA |
|---|---|---|
| P1 | 1 h | 4 h |
| P2 | 4 h | 24 h |
| P3 | 12 h | 72 h |
| P4 | 24 h | 168 h |

The resolution clock starts when the ticket is created and runs on calendar hours
for P1 and P2, and on business hours for P3 and P4.

## Category ownership

| Category | Owning team | Default priority |
|---|---|---|
| plumbing | facility_plumbing | P3 |
| electrical | facility_electrical | P2 |
| civil | facility_civil | P3 |
| lift | vendor_lift | P2 |
| common_area | facility_housekeeping | P4 |
| parking | facility_security | P4 |
| water_supply | facility_plumbing | P2 |
| security | facility_security | P3 |
| warranty_claim | customer_relations | P3 |

## Safety-critical classes

These bypass normal routing. The ticket is raised at P1 and the human on-call
path is notified immediately, regardless of how the request was worded or how
confident the classifier was.

| Hazard class | Description | On-call path |
|---|---|---|
| Gas leak or suspected gas escape | Forced P1, model confidence not consulted | facility_emergency |
| Live electrical hazard | Forced P1, model confidence not consulted | facility_emergency |
| Suspected structural defect | Forced P1, model confidence not consulted | structural_engineering |
| Person trapped in a lift | Forced P1, model confidence not consulted | vendor_lift_emergency |

## Priority assignment rules

Rules are evaluated in order and the first match decides the priority. If no rule
matches, the category default applies. Priority is assigned in code from this
table, not by a language model.

| Rule | Priority | Applies to | Condition |
|---|---|---|---|
| R01 | P1 | water_supply, electrical | Total loss of an essential service to a whole wing or floor |
| R02 | P1 | security | Unauthorised access or a failed access-control device |
| R03 | P2 | plumbing, civil, water_supply, parking | Active water ingress or an overflow damaging the premises |
| R04 | P2 | lift | Lift or shared vertical transport out of service |
| R05 | P2 | electrical, water_supply | Habitability impaired inside the home |
| R06 | P3 | common_area, parking, security, lift | Shared-area service degraded but not unsafe |
| R07 | P3 | warranty_claim | Warranty assessment required on a functional defect |
| R08 | P4 | civil, common_area, parking | Cosmetic or convenience issue |

## Escalation on breach

A ticket that crosses its resolution SLA is escalated to the facility manager and
appears on the leadership dashboard in the breached bucket. Breach does not close
the ticket or reset the clock.
