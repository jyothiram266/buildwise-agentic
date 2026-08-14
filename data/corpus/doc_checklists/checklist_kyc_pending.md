---
source_id: CHK-KYC_PENDING
source_name: Document Checklist — Stage 1 — KYC
collection: doc_checklists
effective_date: 2026-05-11
freshness_days: 180
audience_scope: [customer, resident, sales_staff, legal_finance, manager]
---

# Stage 1 — KYC — Document Checklist

## Required documents

| Document | Type | Required | Notes |
|---|---|---|---|
| PAN card copy of each applicant | `pan_card` | Yes | Self-attested. Name must match the booking form exactly. |
| Aadhaar copy of each applicant | `aadhaar` | Yes | Masked Aadhaar is acceptable. Address page required. |
| Current address proof | `address_proof` | Yes | Utility bill, passport or rental agreement, not older than three months. |
| Passport photograph of each applicant | `photograph` | Yes | Recent, light background. |

## Where to submit

Upload through the customer portal, or hand over at the sales office.

## How completeness is assessed

A stage is complete when every document above is in `submitted` state and no
submitted document has passed its expiry date. An expired document is treated as
a gap, not as a submission: it must be replaced with a current copy.

## Scope of guidance

This checklist is procedural. It states what is required and where it goes. It
does not interpret any clause of the agreement, advise on stamp duty liability,
or comment on the legal effect of a document. Questions of that kind go to the
legal team.
