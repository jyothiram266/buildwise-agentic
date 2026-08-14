# Presentation outline

Twenty minutes. The structure argues one thesis: **the hard part of an agentic
system is not making it answer, it is making the answer trustworthy** — and that
this is an architecture problem rather than a model problem.

---

## 1 · The problem, in one slide (2 min)

A developer's support inbox mixes nine kinds of request from five kinds of person,
and three of those requests are legally consequential. Show the matrix: intent
across the top, actor down the side, and mark the cells where a wrong answer costs
money or trust.

Land this: *the same sentence needs a different answer depending on who sent it, and
some of those answers must be "I am not going to answer that".*

## 2 · Five rules (2 min)

The design rules, stated as constraints rather than features. Say that each one
closes a specific failure mode, then name the failure mode.

## 3 · Live demo (8 min)

Follow `DEMO_SCRIPT.md`, but only these five, in this order:

1. **2BHK under 85 lakhs** — grounded, cited, automatic. Sets the baseline.
2. **1BHK that does not exist** — the honest no, no substitution.
3. **Possession dispute with a refund threat** — tier 3, acknowledgement only. Then
   show the escalation brief in the manager's queue.
4. **Gas smell** — P1, on-call paged, and it works in Hinglish.
5. **Audit replay of case 3** — prompt version, policy version, sources, and the
   append-only guarantee.

Resist showing more. Five moments land; nine blur.

## 4 · The evaluation slide (4 min) — the one that matters

Three numbers, in this order:

| | |
|---|---|
| Intent accuracy, tuned set | **100%** |
| Intent accuracy, held-out set | **19.6%** |
| Misclassified cases still routed to a human | **45 / 45** |

Say: *the first number is worthless and I will tell you why. I tuned the keyword
lists until it passed. The second number is what the thing in the model's slot can
actually do on phrasings it has not seen. The third number is the one I would defend
in front of a regulator.*

Then: *the safety properties do not depend on model quality, and I can only make
that claim because I measured it with a deliberately bad model in the slot.*

This slide is the whole presentation. Do not rush it and do not soften it.

## 5 · What the evaluation caught (2 min)

Five real defects found by suites rather than review: the beam-crack P1 miss, the
lift-entrapment miss, the "sparking"/"parking" substring collision, the invisible
Hinglish hazards, and the overconfident calibration that had silently disabled the
escalation path.

Say: *none of these were found by reading the code. Four of them were in the code I
had just written and was reasonably happy with.*

## 6 · Limits (1 min)

Read the honest list: rule-engine default, synthetic eval data, hand-written graph,
unverified frontend build, stub authentication. Then say what you would do first
with a month and real traffic.

## 7 · Close (1 min)

*Everything expensive in this system is the part that decides when not to answer.
That is also the part that does not need a better model — it needs a policy file, a
SQL predicate and an audit table.*

---

## Questions to have answers ready for

- *Why not just use a bigger model?* → the tiering, ACL and audit layers would be
  identical, and the held-out result shows the guarantees do not rest on the model.
- *What is the cost per case?* → the dashboard shows it per intent; the mock provider
  is zero, so quote real-provider numbers if you have run them.
- *How do you know the ACL works?* → `tests/security/test_acl.py`, and the property
  is that out-of-scope reads return empty rather than an error.
- *What happens when a connector is down?* → two retries, then a labelled partial
  answer or a human handoff. Never a corpus number presented as current.
- *Could a customer prompt-inject their way into someone else's data?* → the
  predicate is built from the scope before any text is read, so a followed
  instruction still reads nothing new. Detection is the outer layer.
