# Demo script

Fifteen minutes, eight journeys, three moments where the system does something
uncomfortable on purpose. Run `make selfcheck` first.

The single most important control on screen is the **"Acting as"** selector. Say
this early: *what changes when I switch identity is what the API returns, not what
the interface hides.*

---

## Setup (30 seconds)

Open http://localhost:3000. Point at the `llm: mock` badge in the header and say:

> This is running a deterministic rule engine in the model's slot — no API key, no
> network. Everything you are about to see about routing, permissions, escalation
> and audit works with a deliberately weak model behind it. That is the point.

---

## 1 · Availability, grounded (UJ-1) — 90s

**As Priya Sharma (prospective buyer):**

> Do you have any 2BHK under 85 lakhs in Whitefield?

Point at:
- the citation chip with the price list id and its **effective date**
- the tier ladder sitting at T0 — this is an automatic answer
- the scope panel on the right: a prospect has no bookings, no units, no projects

Say: *the price came from the inventory system and the wording came from an approved
price sheet. The system is not able to tell you a price that is not in one of those
two places.*

## 2 · The honest no (UJ-1 negative) — 60s

**Same person:**

> Any 1BHK available at Aurora Heights?

Aurora has no 1BHK units. Watch it say so — **and offer nothing instead**.

Say: *every sales assistant demo I have seen answers this with "no 1BHK, but here is
a lovely 2BHK". That is a fabrication about what the customer asked for. It also
distinguishes three different zeros: sold out, not offered here, and not launched
yet. They need different answers.*

## 3 · Customer-safe status (UJ-2) — 90s

**Switch to Rakesh Menon (customer, Aurora Tower B):**

> What is the construction status of my tower?

Point at the percentage, the certification date, and the possession date.

Then say the hard part: *Tower B has an approved revised possession date, so it can
be quoted. Tower E has a revision that management is discussing internally and has
not approved. Ask this as a Palm Meridian customer and you will not get that date —
not because the wording is careful, but because the connector strips the value out
of the payload before the API process ever sees it. There is nothing to leak.*

## 4 · Documents, and the expired one (UJ-3) — 90s

**Same person:**

> What documents are still pending for my registration?

Point at the distinction between **pending** and **expired**.

Say: *his bank sanction letter is on file, and it has expired. A system that reports
"submitted" sends him to the registrar's office to be turned away. Missing and
expired are different states and this answer treats them that way.*

## 5 · The dispute (UJ-4) — 2 min · **first uncomfortable moment**

**Same person:**

> Why has my possession date moved again? I want a refund if this continues.

Watch the tier ladder go to **T3 red** and the reply become an acknowledgement.

Say: *it has deliberately not answered. A refund demand is tier 3, which means
acknowledge, escalate, start the clock, and say nothing about substance. Notice
what is absent: no date, no amount, no apology theatre, no view on who is at fault.
The most valuable thing this system does here is refuse to be helpful.*

**Switch to Kavitha (manager) → Approvals.** Open the escalation. Read the four
headings: case history, what was attempted, risk rationale, recommended next action.

Say: *the rationale quotes the policy rule that fired rather than paraphrasing it.
The escalation row and the SLA clock were written before the brief was generated —
so if language generation had failed, the case would still be owned, still timed,
and still in this queue with a plain fallback brief attached.*

## 6 · One note, two audiences (UJ-5) — 2 min

**Switch to Meera Iyer (site engineer).** Paste a genuinely messy note:

> B blk slab 7 done 60%, curing on. steel short, vendor says 3 days. lift shaft
> measurement mismatch, 40mm off. told them to hold. possession may slip to Mar.

Point at the findings panel — the internal summary keeps the vendor, the 40mm
mismatch and the slip. Then point at the customer-safe version in the same finding.

Say: *the architecture generates separately per audience rather than writing one
answer and redacting it. A redaction step operates on text that already contains
the thing you are trying to protect, so every bug in the redactor is a leak. Here
the internal findings never enter the customer-facing prompt at all.*

## 7 · The vendor who wants a commitment (UJ-6) — 90s · **second uncomfortable moment**

**Switch to Faisal Constructions (contractor):**

> Cement supply has stopped at Tower B, we have zero stock. When will you release
> my payment?

Point at the delay expressed as a **range with assumptions**, and at the complete
absence of any statement about payment.

Say: *two things it will not do. It will not give a single-number delay, because a
number reads as a commitment. And it will not say anything about the payment — not
"we will look into it", not "this will be considered favourably". It names
procurement and stops. An assistant that soothes a vendor has made a commercial
commitment nobody authorised.*

## 8 · The leak, and the gas smell (UJ-7) — 2 min · **third uncomfortable moment**

**Switch to Sunita Rao (resident):**

> There is water leaking from the bathroom ceiling and it is spreading.

Point at: category plumbing, priority **P2**, ticket id, SLA due, assigned team.

Say: *the model named the category. Code assigned the priority, from a rule in a
YAML file, matching on the resident's own words — "leaking", "spreading". Not the
model's paraphrase, because a paraphrase can drop the word that makes it urgent.*

Then, same person:

> I can smell gas near the kitchen pipe.

**P1. Safety-critical. On-call paged. Tier 3.**

Say: *this bypasses everything. It does not matter how confident the categoriser
was. And it works in Hinglish — "gas ka smell aa raha hai" hits the same path,
because the residents most likely to be reporting a real emergency are not
necessarily writing formal English. That gap was found by the evaluation suite,
not by review.*

## 9 · Ranked follow-ups (UJ-8) — 60s

**Switch to Deepak Verma (sales executive):**

> Who should I follow up with today?

Point at the reason codes on each row.

Say: *the ranking is arithmetic over CRM fields, and every position shows the codes
that produced it. A model-generated ordering with a model-generated justification
cannot be checked by the person acting on it.*

## 10 · The audit trail — 2 min

**As Kavitha → Audit.** Paste the case id from the possession dispute.

Walk the spine top to bottom: masking, classification, router, risk engine,
escalation, gate. Point at the prompt version, policy version and model on each
step, and the source ids.

Say: *given a case id, this reconstructs which prompt version, which policy version,
which model and which documents produced the answer that was sent. The trace table
refuses updates and deletes at the database level, not in application code. And if
a step cannot be explained from these rows, the viewer says "gaps in trace" rather
than filling it in from somewhere else.*

## 11 · Operations — 90s

**Kavitha → Operations.**

Point at automation rate **next to** refusal rate.

Say: *those two live side by side deliberately. A system can look perfectly grounded
by refusing everything. And the override rate has the rejection reasons under it,
because the rate tells you there is a problem and the reasons tell you which agent
to fix.*

---

## If someone asks the sharp question

**"How accurate is the intent classification?"**

> On the tuned set, 100%. That number is worthless — I adjusted the keyword lists
> until it passed. On a held-out set written to defeat those lists, using the
> colloquial English customers actually send, it gets **19.6%**.
>
> Here is what makes that acceptable rather than embarrassing: of the 45 held-out
> messages it got wrong, **all 45 still reached a human.** Forty-three because
> confidence fell below threshold, two because the risk engine matched a tier-3
> phrase against the raw text independently of the intent. Zero were answered
> automatically with a confident wrong answer.
>
> The safety properties do not depend on model quality. I can only say that because
> I measured it with a deliberately bad model in the slot. Put a real model in and
> the accuracy improves; the guarantees were never resting on it.

**"What happens if the model returns nonsense?"**

> One repair attempt against the schema, then the case goes to a human. Not two —
> a second repair on the same malformed output rarely works and doubles latency on
> the path where the system is already misbehaving.

**"Could someone prompt-inject it through a site report?"**

> Two of the seeded site reports contain injection probes. They are detected at
> retrieval time and reach the model labelled as quoted data. But the layer that
> actually matters is that authorisation is a SQL predicate built from the caller's
> scope — so an instruction that is followed still cannot read a row the actor
> could not read anyway. Detection is the outer layer; the predicate is the wall.
