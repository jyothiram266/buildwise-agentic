"""Deterministic offline provider.

This is what runs when `LLM_PROVIDER=mock`. It produces schema-valid, grounded
output for every registered prompt using rules over the same typed facts a real
model would receive. It exists for three reasons:

1. The prototype must run end-to-end on a reviewer's machine with no API key.
2. Tests need a provider with zero network calls and stable output. Non-determinism
   in a test suite that guards safety properties is worse than no test suite.
3. It makes the boundary visible: everything the system does *around* the model —
   routing, ACL, risk tiering, approval, audit — is provably independent of model
   quality, because it all still works with a rule engine in the model's place.

What it is not: a language model. It composes prose from facts rather than
understanding them. Classification here is keyword scoring, so the eval harness
labels every number with the provider that produced it, and a real provider is a
one-line config change.

Contract with the prompts: every handler returns a JSON string matching the schema
its prompt declares. When a prompt's schema changes, the handler changes with it —
`tests/unit/test_mock_provider.py` asserts the pairing.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

INTENT_SIGNALS: dict[str, list[tuple[str, float]]] = {
    "SALES_INQUIRY": [
        ("which projects", 2.4), ("what projects", 2.2), ("do you have in", 2.4),
        ("projects do you have", 2.8), ("hoarding", 2.0), ("on offer", 2.0),
        ("east facing", 1.8), ("west facing", 1.8), ("suit us", 1.6), ("family of", 1.4),
        ("would like to visit", 2.2), ("for around", 1.6),
        ("available", 2.0), ("availability", 2.0), ("looking for", 2.0), ("interested in buying", 2.5),
        ("price", 1.6), ("pricing", 1.8), ("price list", 2.2), ("rate", 1.0), ("cost of", 1.4),
        ("brochure", 2.2), ("floor plan", 2.2), ("amenities", 2.2), ("site visit", 2.0),
        ("budget", 1.8), ("inventory", 1.8), ("2bhk", 1.2), ("3bhk", 1.2), ("1bhk", 1.2),
        ("villa", 1.0), ("discount", 1.4), ("offer", 0.8), ("carpet area", 1.4),
        ("what projects", 2.0), ("show me", 1.2), ("any units", 2.0), ("commercial floor", 1.6),
    ],
    "BOOKING": [
        ("put a hold", 3.6), ("hold on a", 2.6), ("booked unit", 3.2), ("i booked", 2.8),
        ("where does it stand", 2.6), ("allotment letter", 3.0), ("allotted unit", 3.0),
        ("higher floor", 2.2), ("before agreement", 1.8), ("change my allotted", 3.2),
        ("my booking", 2.4), ("booking status", 2.6), ("book a", 2.0), ("booking form", 2.2),
        ("allotment", 2.4), ("hold the unit", 2.4), ("blocked unit", 2.0), ("token amount", 2.0),
        ("cancel my booking", 2.0), ("transfer my booking", 2.6), ("change my unit", 2.4),
        ("booked a", 1.6), ("reserve", 1.6),
    ],
    "DOCUMENTATION": [
        ("identity proof", 2.8), ("co-applicant", 2.4), ("affidavit", 2.6),
        ("address proof", 2.4), ("passport copy", 2.2), ("received against", 2.4),
        ("mandatory for", 1.8), ("do you need my", 2.0),
        ("document", 2.2), ("documents", 2.4), ("paperwork", 2.2), ("kyc", 2.2),
        ("checklist", 2.4), ("what is pending for", 2.2), ("submitted", 1.8), ("submit", 1.4),
        ("registration", 1.8), ("agreement", 1.4), ("stamp duty", 2.0), ("encumbrance", 2.2),
        ("sanction letter", 2.0), ("expired", 1.6), ("upload", 1.6), ("notarised", 1.8),
        ("witness", 1.6), ("pan card", 2.0), ("aadhaar", 2.0),
    ],
    "PAYMENT": [
        ("what do i still owe", 3.0), ("still owe", 2.6), ("outstanding", 2.4),
        ("dues", 2.8), ("total consideration", 2.6), ("disbursed", 2.6),
        ("reflected against", 2.4), ("payment plan", 2.4), ("paid so far", 2.6),
        ("my account", 1.6), ("bank has", 2.0),
        ("payment", 2.2), ("paid", 1.8), ("demand note", 2.6), ("instalment", 2.2),
        ("installment", 2.2), ("outstanding", 2.2), ("receipt", 2.0), ("emi", 2.0),
        ("disbursement", 2.0), ("amount due", 2.4), ("overdue", 2.2), ("interest", 1.6),
        ("payment schedule", 2.6), ("milestone payment", 2.4), ("ledger", 1.8), ("invoice", 1.2),
    ],
    "CONSTRUCTION_STATUS": [
        ("what stage", 2.6), ("stage is construction", 2.8), ("progress update", 2.6),
        ("how far along", 2.6), ("percentage of the structure", 2.6),
        ("has the slab", 2.4), ("which milestone", 2.6),
        ("progress", 2.2), ("construction status", 2.8), ("milestone", 2.2), ("slab", 1.8),
        ("structure", 1.4), ("possession date", 2.0), ("handover", 1.8), ("when will it be ready", 2.4),
        ("completion", 1.6), ("status of tower", 2.6), ("how far", 1.8), ("update on tower", 2.4),
        ("percentage complete", 2.2), ("finishing work", 1.8), ("site progress", 2.4),
    ],
    "MAINTENANCE": [
        ("smell gas", 3.0), ("smell of gas", 3.0), ("gas ka smell", 3.0), ("smell", 1.4),
        ("sparking", 2.6), ("spark", 2.0), ("shock", 2.4), ("burning smell", 2.8),
        ("stuck in the lift", 3.0), ("stuck inside lift", 3.0), ("trapped", 2.4),
        ("kitchen pipe", 2.2), ("bathroom ceiling", 2.4), ("water is leaking", 2.8),
        ("dripping", 2.4), ("seepage", 2.6), ("choked", 2.6),
        ("snag", 2.6), ("hinge", 2.4), ("jamming", 2.6), ("door lock", 2.6),
        ("stopped working", 2.4), ("has not been collected", 2.4), ("someone look at it", 2.0),
        ("in my flat", 1.6), ("in my bathroom", 1.8), ("on my floor", 1.6),
        ("out of service", 2.2), ("no supply", 2.0), ("since yesterday", 1.4),
        ("since morning", 1.4),
        ("leak", 2.4), ("leaking", 2.6), ("not working", 2.2), ("broken", 2.2), ("repair", 2.2),
        ("fix", 1.6), ("choked", 2.4), ("crack", 2.2), ("seepage", 2.4), ("sparks", 2.4),
        ("no power", 2.2), ("no water", 2.2), ("smell of gas", 2.8), ("lift", 1.6),
        ("stuck in", 2.4), ("maintenance", 2.0), ("ticket", 1.4), ("water supply", 2.0),
        ("cctv", 1.8), ("intercom", 1.8), ("garbage", 1.8), ("warranty", 1.6), ("tripped", 2.0),
        ("dripping", 2.2), ("blocked drain", 2.4), ("burning smell", 2.6),
    ],
    "CONTRACTOR_UPDATE": [
        ("supply has stopped", 3.0), ("zero stock", 3.0), ("stock is finished", 2.8),
        ("consignment", 2.6), ("release my payment", 2.4), ("release the payment", 2.4),
        ("waterlogged", 2.8), ("no work possible", 3.0), ("on site", 1.8), ("the site", 1.6),
        ("reported today", 2.6), ("against a planned", 2.8), ("broken down", 2.4),
        ("we finished", 2.8), ("delivery is delayed", 2.8), ("curing", 2.6),
        ("ra bill", 3.0), ("hoist", 2.6), ("requesting an extension", 2.8),
        ("waterproofing", 2.4), ("terrace is complete", 2.4), ("our stock", 2.8),
        ("labourers", 2.6), ("slab work on", 2.6), ("completed to", 2.2),
        ("lifting work", 2.4), ("is pending, when", 2.0),
        ("cement", 2.0), ("material shortage", 2.8), ("manpower", 2.4), ("crew", 2.0),
        ("our team", 1.8), ("we have completed", 2.2), ("slab poured", 2.4), ("blocker", 2.4),
        ("work package", 2.6), ("consignment", 2.0), ("supply", 1.4), ("shuttering", 2.2),
        ("subcontractor", 2.4), ("rebar", 2.0), ("batching plant", 2.2), ("progress report", 1.8),
        ("labour", 2.0), ("vendor", 1.6),
    ],
    "COMPLAINT_ESCALATION": [
        ("asked twice", 3.0), ("got nothing back", 2.8), ("following up again", 2.6),
        ("nobody has responded", 2.8), ("no explanation", 2.4),
        ("refund", 2.8), ("legal notice", 3.0), ("lawyer", 2.6), ("advocate", 2.4),
        ("consumer court", 3.0), ("consumer forum", 3.0), ("rera complaint", 2.8),
        ("unacceptable", 2.6), ("third time", 2.6), ("fourth time", 2.6), ("no one has responded", 2.8),
        ("nobody replied", 2.6), ("escalate", 2.4), ("compensation", 2.6), ("cheated", 2.8),
        ("fraud", 2.8), ("social media", 2.4), ("twitter", 2.2), ("press", 1.8),
        ("dispute", 2.2), ("wrongly charged", 2.6), ("i want to complain", 2.8),
        ("who is accountable", 2.6), ("this is ridiculous", 2.4), ("frustrated", 1.8),
        ("keeps getting postponed", 2.4), ("why has possession moved", 2.6),
    ],
    "OTHER": [
        ("gst registration", 3.2), ("copy of your", 2.4), ("office open", 2.8),
        ("thanks for", 2.6), ("thank you", 2.4), ("who is the", 2.0),
        ("add my new phone", 2.8), ("update my records", 2.4), ("for my records", 2.2),
        ("hello", 2.2), ("hi there", 2.2), ("relations manager", 2.4),
    ],
}

URGENCY_HIGH = (
    "urgent", "immediately", "emergency", "right now", "asap", "stuck", "trapped",
    "unsafe", "today", "gas", "sparks", "burning", "flooding", "spreading",
)
NEGATIVE = (
    "unacceptable", "ridiculous", "frustrated", "angry", "disappointed", "worst",
    "cheated", "fraud", "pathetic", "disgusted", "fed up", "no one has responded",
    "third time", "refund", "legal", "complaint", "dispute", "postponed", "still not",
)
POSITIVE = ("thank", "appreciate", "great", "happy", "excellent", "well done", "pleased")

_UNIT_RE = re.compile(r"\b(BW-[A-Z0-9]+-\d{3,4}|[A-Z]-\d{3,4})\b")
_TOWER_RE = re.compile(r"\b(?:tower|block|wing)\s+([A-Za-z0-9]{1,3})\b", re.I)
_CUSTOMER_RE = re.compile(r"\b(CUST-\d{3,6})\b")
_BOOKING_RE = re.compile(r"\b(BK-\d{3,6})\b")
_CONFIG_RE = re.compile(r"\b([1-4])\s?bhk\b", re.I)
_PROJECT_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+"
    r"(?:Heights|Meridian|Commons|Grove|Villas|Residency|Enclave|Gardens|Towers))\b"
)


#: A configuration and a budget in the same message is a buying enquiry, whatever
#: the surrounding phrasing. Scored as a compound signal because the individual
#: tokens are weak on their own — "2BHK" alone could be a maintenance complaint
#: about a 2BHK, and "85 lakhs" alone could be a payment question.
_MONEY_HINT = re.compile(r"\b\d+(?:\.\d+)?\s*(?:lakh|lakhs|lac|lacs|cr|crore|crores)\b", re.I)
_ASKING = ("do you have", "is there any", "are there any", "looking for", "any options",
           "what do you have", "show me", "suggest", "available")


@lru_cache(maxsize=4096)
def _pattern(phrase: str) -> re.Pattern[str]:
    """Word-boundary matcher for a signal phrase.

    Plain substring matching produced two real misclassifications the eval set
    caught: "sparking" contains "parking", and "tiles have lifted" contains "lift".
    A trailing "*" marks a deliberate prefix match (so "landscap*" still catches
    landscaping and landscaped).
    """
    if phrase.endswith("*"):
        return re.compile(r"\b" + re.escape(phrase[:-1]), re.I)
    return re.compile(r"\b" + re.escape(phrase) + r"\b", re.I)


def _hit(text: str, phrase: str) -> bool:
    return _pattern(phrase).search(text) is not None


def _score_intents(text: str) -> dict[str, float]:
    low = text.lower()
    scores: dict[str, float] = {}
    for intent, signals in INTENT_SIGNALS.items():
        total = 0.0
        for phrase, weight in signals:
            if _hit(low, phrase):
                total += weight
        if total:
            scores[intent] = total

    # A tower or block reference next to a progress word is a construction question,
    # whatever else the sentence contains. Scored as a pair because "status" alone is
    # ambiguous (status of a booking, a payment, a ticket) and a tower name alone is
    # not a question.
    if re.search(r"\b(?:tower|block|blk|wing)\s*[a-f]\b", low) and any(
        word in low for word in ("status", "progress", "how far", "stage", "complete", "update")
    ):
        scores["CONSTRUCTION_STATUS"] = scores.get("CONSTRUCTION_STATUS", 0.0) + 2.2

    has_config = bool(_CONFIG_RE.search(low)) or "villa" in low
    has_budget = bool(_MONEY_HINT.search(low))
    # A configuration named inside a question is an availability question, even
    # without an explicit verb: "Any 1BHK at Aurora Heights?" is the shortest real
    # form of UJ-1 and must not fall to triage.
    is_asking = any(phrase in low for phrase in _ASKING) or (has_config and "?" in text)
    # A booking-specific verb outranks the compound sales signal: "put a hold on a
    # villa" mentions a configuration but is a booking request, not an enquiry.
    booking_intent = any(
        _hit(low, phrase)
        for phrase in ("put a hold", "hold on a", "booked unit", "i booked", "allotment",
                       "allotted unit", "transfer my booking", "cancel my booking")
    )
    if has_config and (has_budget or is_asking) and not booking_intent:
        scores["SALES_INQUIRY"] = scores.get("SALES_INQUIRY", 0.0) + (
            3.0 if has_budget and is_asking else 2.2
        )
    return scores


def classify(variables: dict[str, Any]) -> str:
    text = str(variables.get("request", ""))
    low = text.lower()
    scores = _score_intents(text)

    if not scores:
        intent, secondary, confidence = "OTHER", None, 0.35
    else:
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        intent = ranked[0][0]
        top = ranked[0][1]
        runner = ranked[1][1] if len(ranked) > 1 else 0.0

        # A grievance about a topic is a grievance first. This boundary
        # (CONSTRUCTION_STATUS vs COMPLAINT_ESCALATION) is the one the build plan
        # calls out as the one that hurts in a demo.
        if "COMPLAINT_ESCALATION" in scores and scores["COMPLAINT_ESCALATION"] >= 2.4:
            if intent != "COMPLAINT_ESCALATION":
                runner = max(runner, top)
                intent = "COMPLAINT_ESCALATION"
                top = scores["COMPLAINT_ESCALATION"]

        secondary = None
        for name, value in ranked:
            if name != intent and value >= 2.0 and value >= top * 0.45:
                secondary = name
                break

        margin = (top - runner) / top if top else 0.0
        # Calibration matters more than it looks: the risk engine routes anything
        # below 0.70 to a human, so a scorer that saturates at 0.95 silently
        # disables that path. The ceiling is 0.88 because keyword scoring cannot
        # justify more, and a strong signal with a close runner-up scores lower
        # than a strong signal standing alone.
        confidence = 0.38 + min(0.32, top / 18.0) + 0.18 * margin
        if len(text.split()) < 5:
            confidence -= 0.12
        if "?" in text and len(text.split()) < 8:
            confidence -= 0.04
        if secondary:
            confidence -= 0.04
        confidence = round(max(0.2, min(0.88, confidence)), 2)

    entities: dict[str, str] = {}
    if m := _PROJECT_RE.search(text):
        entities["project"] = m.group(1)
    if m := _TOWER_RE.search(text):
        entities["tower"] = m.group(1).upper()
    if m := _UNIT_RE.search(text):
        entities["unit"] = m.group(1)
    if m := _CUSTOMER_RE.search(text):
        entities["customer_id"] = m.group(1)
    if m := _BOOKING_RE.search(text):
        entities["booking_id"] = m.group(1)
    if m := _CONFIG_RE.search(text):
        entities["config"] = f"{m.group(1)}BHK"
    if "villa" in low:
        entities.setdefault("config", "villa")
    if amount := re.search(r"(\d+(?:\.\d+)?)\s*(?:lakh|lac|l\b|cr|crore)", low):
        entities["budget_text"] = amount.group(0)
    entities["urgency"] = "high" if any(w in low for w in URGENCY_HIGH) else "normal"

    negative = sum(1 for w in NEGATIVE if w in low)
    positive = sum(1 for w in POSITIVE if w in low)
    sentiment = "negative" if negative > positive else "positive" if positive else "neutral"

    return json.dumps(
        {
            "intent": intent,
            "secondary_intent": secondary,
            "confidence": confidence,
            "entities": entities,
            "sentiment": sentiment,
        }
    )


# ---------------------------------------------------------------------------
# Maintenance categorisation
# ---------------------------------------------------------------------------

#: Category signals in three tiers, because flat keyword counting produced the
#: wrong answer on real phrasings the eval set caught:
#:
#:   DEVICE  — names a specific system (cctv, intercom, lift). Most specific, wins.
#:   PLACE   — names where the problem is (corridor, basement). Beats the trade,
#:             because "corridor lights" is a common-area job, not an electrical one.
#:   TRADE   — names the craft involved (wiring, tiles, pipe). Weakest signal: it
#:             describes the fix, not the request.
DEVICE_SIGNALS: dict[str, tuple[str, ...]] = {
    "lift": ("lift", "elevator"),
    "security": ("cctv", "camera feed", "intercom", "boom barrier", "access card",
                 "visitor entry", "security guard", "gate"),
    "water_supply": ("water supply", "no water", "water pressure", "borewell", "tanker",
                     "overhead tank", "muddy", "water tank", "supply is"),
    "parking": ("parking", "parking slot", "car park", "basement ramp", "visitor parking"),
    "warranty_claim": ("under warranty", "within warranty", "claim under", "in warranty"),
}

PLACE_SIGNALS: dict[str, tuple[str, ...]] = {
    "common_area": ("corridor", "lobby", "staircase", "clubhouse", "play area", "garden",
                    "landscap*", "terrace common", "garbage", "chute", "gym", "swimming pool",
                    "our floor", "seventh floor", "common area"),
    "parking": ("basement", "ramp", "stilt"),
}

TRADE_SIGNALS: dict[str, tuple[str, ...]] = {
    "plumbing": ("leak", "leaking", "drain", "sink", "flush", "tap", "pipe", "sewage",
                 "choked", "drainage", "toilet", "bathroom", "shower", "dripping",
                 "seepage", "geyser", "faucet", "cistern"),
    "electrical": ("socket", "switch", "mcb", "power", "light", "lights", "wiring", "spark",
                   "shock", "short circuit", "doorbell", "ac point", "electrical", "tripped",
                   "burning", "distribution board", "bulb", "fan"),
    "civil": ("crack", "tile", "tiles", "plaster", "paint", "peeling", "door frame", "window",
              "damp", "beam", "column", "flooring", "waterproofing", "shutter", "hinge",
              "snag", "lock is jamming", "jamming", "door lock", "handle", "latch"),
    "common_area": ("not collected", "swing", "bench"),
}

#: Severity phrases come from the policy file rather than a second list here.
#: The deterministic engine matches on these exact strings, so any divergence
#: between what this provider quotes and what the policy matches would be an
#: invisible bug: the quoted signals would look fine while the priority was wrong.
_POLICY_PATH = Path(__file__).resolve().parents[1] / "governance" / "policies" / "severity_matrix.yaml"


@lru_cache
def severity_phrases() -> tuple[str, ...]:
    try:
        matrix = yaml.safe_load(_POLICY_PATH.read_text()) or {}
    except OSError:  # pragma: no cover - policy file is part of the package
        return ()
    phrases: set[str] = set()
    for spec in (matrix.get("safety_critical") or {}).values():
        phrases.update(spec.get("keywords", []))
        for pair in spec.get("co_occurrence", []):
            phrases.update(pair)
    for rule in matrix.get("rules") or []:
        phrases.update(rule.get("any_keywords", []))
    return tuple(sorted(phrases, key=len, reverse=True))


def maintenance(variables: dict[str, Any]) -> str:
    text = str(variables.get("request", ""))
    low = text.lower()

    scores: dict[str, float] = {}

    def add(table: dict[str, tuple[str, ...]], weight: float) -> None:
        for category, signals in table.items():
            hits = sum(1 for signal in signals if _hit(low, signal))
            if hits:
                scores[category] = scores.get(category, 0.0) + weight * min(hits, 3)

    add(TRADE_SIGNALS, 1.0)
    add(PLACE_SIGNALS, 2.0)
    add(DEVICE_SIGNALS, 3.5)

    if not scores:
        category, confidence = "civil", 0.35
    else:
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        category = ranked[0][0]
        # An explicit warranty ask wins over the underlying trade, per the prompt.
        if any(
            phrase in low for phrase in ("under warranty", "within warranty", "claim under", "in warranty")
        ):
            category = "warranty_claim"
        top = ranked[0][1]
        runner = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = (top - runner) / top if top else 0.0
        confidence = round(min(0.9, 0.5 + min(0.22, top / 14.0) + 0.18 * margin), 2)

    signals = [phrase for phrase in severity_phrases() if _hit(low, phrase)]
    summary = (
        f"Resident reports an issue categorised as {category.replace('_', ' ')}. "
        f"Reported wording: {text.strip()[:180]}"
    )
    return json.dumps(
        {
            "category": category,
            "severity_signals": signals[:6],
            "summary": summary,
            "confidence": confidence,
        }
    )


# ---------------------------------------------------------------------------
# Prose handlers — compose from typed facts, never from memory
# ---------------------------------------------------------------------------


def _fact(variables: dict[str, Any]) -> dict[str, Any]:
    facts = variables.get("facts")
    if isinstance(facts, str):
        try:
            return json.loads(facts)
        except json.JSONDecodeError:
            return {}
    return facts or {}


def _money(amount: Any) -> str:
    try:
        value = int(amount)
    except (TypeError, ValueError):
        return str(amount)
    if value >= 10_000_000:
        return f"INR {value:,} ({value / 10_000_000:.2f} Cr)"
    return f"INR {value:,} ({value / 100_000:.2f} L)"


def property_info(variables: dict[str, Any]) -> str:
    facts = _fact(variables)
    units = facts.get("units") or []
    count = int(facts.get("match_count") or 0)
    asked = facts.get("query") or {}

    if facts.get("commercial_request"):
        summary = (
            "Published prices come from the current approved price list, and a discount, waiver or "
            "negotiated rate is not something this channel can quote. A sales executive can take "
            "that conversation forward and will hold the commercial discussion with you directly."
        )
        return json.dumps(
            {"summary": summary, "next_action": "connect_to_sales_executive", "confidence": 0.9}
        )

    if count == 0:
        if facts.get("project_status") == "pre_launch":
            summary = (
                f"{facts.get('project_name', 'This project')} has not launched, so no inventory has "
                "been released for sale yet. Your interest can be recorded as an expression of "
                "interest and you will be contacted when units are released."
            )
        elif facts.get("config_exists_in_project") is False:
            summary = (
                f"{asked.get('config', 'That configuration')} is not offered at "
                f"{facts.get('project_name', 'this project')}. The configurations available here are "
                f"{', '.join(facts.get('configs_available') or []) or 'listed in the project brochure'}. "
                "Nothing else has been substituted for it in this answer."
            )
        else:
            summary = (
                f"There are no available units matching that request at "
                f"{facts.get('project_name', 'the project')} right now — the matching inventory is "
                "fully booked or sold. Rather than offer a different configuration, the honest "
                "position is that this specific requirement has no match today."
            )
        return json.dumps(
            {"summary": summary, "next_action": "offer_alternatives_with_sales", "confidence": 0.86}
        )

    first = units[0]
    prices = [int(u["all_in_price"]) for u in units]
    stale_note = ""
    if facts.get("price_stale"):
        stale_note = (
            f" This price list carries an effective date of {facts.get('price_effective_date')} "
            "and may have been superseded, so please treat it as indicative until confirmed."
        )
    budget_note = ""
    if asked.get("budget_max"):
        budget_note = f" within a budget of {_money(asked['budget_max'])}"

    summary = (
        f"There are {count} available {first['config']} units at {first['project_name']}, "
        f"{first['locality'] or first['city']}{budget_note}. All-inclusive prices in the matching "
        f"set run from {_money(min(prices))} to {_money(max(prices))}, taken from price list "
        f"{facts.get('price_ref')} effective {facts.get('price_effective_date')}. "
        f"As an example, unit {first['unit_id']} in {first['tower_name']} is a {first['config']} of "
        f"{first['carpet_area']} sq ft carpet on floor {first['floor']}, {first['facing']} facing, at "
        f"{_money(first['all_in_price'])} all-inclusive. "
        f"Possession for this project is planned for {facts.get('planned_possession', 'a date given in the brochure')}."
        f"{stale_note}"
    )
    return json.dumps({"summary": summary, "next_action": "offer_site_visit", "confidence": 0.88})


def documentation(variables: dict[str, Any]) -> str:
    facts = _fact(variables)
    if facts.get("clause_interpretation_requested"):
        return json.dumps(
            {
                "summary": (
                    "What a clause in the agreement means is a legal question, and interpretation is "
                    "handled by the legal team rather than through this channel. On the procedural "
                    "side, the document set for your current stage and where each item is submitted "
                    "is set out below, and that part can be answered here."
                ),
                "next_action": "route_to_legal",
                "confidence": 0.88,
            }
        )

    stage = facts.get("stage_label") or facts.get("stage") or "your current stage"
    missing = facts.get("missing") or []
    expired = facts.get("expired") or []
    submitted = facts.get("submitted") or []

    if not missing and not expired:
        summary = (
            f"Your booking is at the {stage} stage and every document required for it is on record "
            f"({len(submitted)} items submitted). Nothing is outstanding from your side at this stage."
        )
        return json.dumps({"summary": summary, "next_action": None, "confidence": 0.9})

    parts = [f"Your booking is at the {stage} stage."]
    if missing:
        parts.append(
            f"{len(missing)} item{'s' if len(missing) > 1 else ''} still to be submitted: "
            f"{_readable(missing)}."
        )
    if expired:
        parts.append(
            f"{_readable(expired)} {'have' if len(expired) > 1 else 'has'} expired, which counts as a "
            "gap rather than a submission and needs a fresh copy."
        )
    parts.append(f"{len(submitted)} document(s) are already on record and need no action.")
    if facts.get("where_to_submit"):
        parts.append(facts["where_to_submit"])
    return json.dumps(
        {
            "summary": " ".join(parts),
            "next_action": "offer_reminder_draft",
            "confidence": 0.9,
        }
    )


def _readable(items: list[str]) -> str:
    pretty = [i.replace("_", " ") for i in items]
    if len(pretty) == 1:
        return pretty[0]
    return ", ".join(pretty[:-1]) + " and " + pretty[-1]


def construction_customer(variables: dict[str, Any]) -> str:
    facts = _fact(variables)
    tower = facts.get("tower_name", "the tower")
    project = facts.get("project_name", "the project")
    pct = facts.get("pct_complete")
    current = facts.get("current_milestone")
    nxt = facts.get("next_milestone")
    certified = facts.get("last_certified")

    parts = [
        f"{tower} at {project} is at {pct}% overall milestone completion as certified on {certified}."
        if pct is not None
        else f"Progress for {tower} at {project} is tracked by milestone."
    ]
    if current:
        parts.append(f"The milestone in progress is {current}.")
    if nxt:
        parts.append(f"Next in sequence is {nxt}.")

    approved = facts.get("approved_revised_possession")
    if approved:
        parts.append(
            f"The current possession date on record for this tower is {approved}, which is an "
            "approved revision to the original plan."
        )
    elif facts.get("slip_days") and int(facts["slip_days"]) > 0:
        parts.append(
            "The schedule has moved against the original plan and a revised date is under review. "
            "A confirmed date is not available yet, so none is being stated here."
        )
    else:
        parts.append(f"The planned possession on record is {facts.get('planned_possession')}.")

    causes = facts.get("cause_categories") or []
    if causes:
        parts.append(f"The factors affecting the schedule fall under {_readable(causes)}.")
    if facts.get("stale"):
        parts.append("This position is older than its freshness window, so a fresher update may exist.")

    return json.dumps(
        {"summary": " ".join(parts), "next_action": "offer_site_visit_or_update", "confidence": 0.85}
    )


def construction_internal(variables: dict[str, Any]) -> str:
    facts = _fact(variables)
    lines = [
        f"{facts.get('tower_name')} / {facts.get('project_name')}: "
        f"{facts.get('milestones_complete')}/{facts.get('milestones_total')} milestones complete, "
        f"{facts.get('pct_complete')}% average completion.",
    ]
    if facts.get("current_milestone"):
        lines.append(f"In progress: {facts['current_milestone']}.")
    if facts.get("slip_days"):
        lines.append(
            f"Maximum slip against plan is {facts['slip_days']} days on "
            f"{_readable(facts.get('slipped_milestones') or ['the affected milestones'])}."
        )
    for blocker in facts.get("blockers") or []:
        lines.append(
            f"Blocker {blocker.get('blocker_id')} [{blocker.get('category')}, "
            f"{blocker.get('severity')}] raised {blocker.get('raised_on')}: "
            f"{blocker.get('description')}"
        )
    if facts.get("approved_revised_possession"):
        lines.append(
            f"Approved revised possession: {facts['approved_revised_possession']} (disclosable)."
        )
    if facts.get("unapproved_revised_possession"):
        lines.append(
            f"Internally discussed date {facts['unapproved_revised_possession']} is NOT approved "
            "and must not be disclosed or implied to a customer."
        )
    if facts.get("injection_flagged"):
        lines.append("flagged: instruction-like content in source site report; not acted on.")
    if facts.get("report_excerpts"):
        lines.append(f"Latest engineer notes on file: {len(facts['report_excerpts'])} report(s) reviewed.")

    return json.dumps({"summary": " ".join(lines), "next_action": "review_blockers", "confidence": 0.87})


def contractor(variables: dict[str, Any]) -> str:
    facts = _fact(variables)
    text = str(variables.get("request", "")).lower()

    category = facts.get("detected_category") or "none"
    severity = facts.get("severity") or "medium"
    impacted = facts.get("impacted_milestones") or []
    commitment = bool(facts.get("commitment_requested"))

    low, high = 0, 0
    assumptions: list[str] = []
    if impacted:
        base = {"low": 2, "medium": 5, "high": 10, "critical": 18}.get(severity, 5)
        low, high = base, int(base * 2.2)
        assumptions = [
            "assumes the blocker is cleared within the current reporting fortnight",
            "assumes no additional dependency slips in the same sequence",
            "range widens if downstream milestones are already at risk",
        ]
        impact = (
            f"Reported {category.replace('_', ' ')} at {severity} severity correlates to "
            f"{len(impacted)} milestone(s): {', '.join(impacted)}. On current information the "
            f"schedule impact is estimated at {low} to {high} days. This is an estimate against "
            "stated assumptions, not a revised date."
        )
    else:
        impact = (
            "The update does not correlate to a milestone in the project register, so a schedule "
            "impact cannot be estimated from what was reported. No range is being given."
        )

    summary = impact
    if commitment:
        summary += (
            " The update also asks for a commitment on payment, timeline or scope. No commitment is "
            "made here; procurement owns that decision and will respond separately."
        )
    if any(w in text for w in ("cement", "steel", "material", "consignment", "supply")):
        summary += " Material position has been logged against the work package."

    return json.dumps(
        {
            "blocker_category": category,
            "severity": severity,
            "impact_statement": impact,
            "delay_estimate_low_days": low,
            "delay_estimate_high_days": high,
            "assumptions": assumptions,
            "commitment_requested": commitment,
            "summary": summary,
            "confidence": 0.82,
        }
    )


def escalation_brief(variables: dict[str, Any]) -> str:
    facts = _fact(variables)
    request = str(variables.get("request", "")).strip()
    triggers = facts.get("triggers") or []
    findings = facts.get("findings") or []
    gaps = facts.get("gaps") or []

    attempted = "\n".join(
        f"- {f.get('agent')}: {f.get('status')} — {str(f.get('summary', ''))[:220]}" for f in findings
    ) or "- No specialist agent produced a usable finding."

    brief = f"""## Case history

{facts.get('actor_role', 'The actor')} raised case {facts.get('case_id')} through {facts.get('channel')}, classified as {facts.get('intent')}{' with a secondary intent of ' + str(facts.get('secondary_intent')) if facts.get('secondary_intent') else ''}. In their words: "{request[:400]}"{' Prior contact on record: ' + str(facts.get('prior_contacts')) + ' case(s) in the last 24 hours.' if facts.get('prior_contacts') else ''}

## What was attempted

{attempted}
{('- Data gap: ' + '; '.join(gaps)) if gaps else ''}

## Risk rationale

Policy assigned tier {facts.get('risk_tier')} of type {facts.get('escalation_type')} because the following trigger(s) matched: {', '.join(triggers) if triggers else 'uncertainty in the pipeline rather than content risk'}. Routing goes to {facts.get('owner_team')} with a {facts.get('sla_hours')} hour response commitment under the escalation routing matrix.

## Recommended next action

{facts.get('owner_team')} should make first contact within the SLA window and confirm the factual position from the systems of record before responding on substance. Until that happens, nothing beyond the acknowledgement already sent should be communicated — in particular no date, no amount, and no view on liability."""

    return json.dumps({"brief": brief, "confidence": 0.86})


def _findings_list(variables: dict[str, Any]) -> list[dict[str, Any]]:
    findings = variables.get("findings")
    if isinstance(findings, str):
        try:
            return json.loads(findings)
        except json.JSONDecodeError:
            return []
    return findings or []


def response_generic(variables: dict[str, Any], audience: str) -> str:
    findings = _findings_list(variables)
    usable = [f for f in findings if f.get("status") == "ok" and f.get("summary")]

    if not usable:
        text = (
            "I don't have a grounded answer to that from the approved sources available to me, so "
            "rather than guess I would rather hand this to a person who can check it properly. "
            "Would you like me to pass it to the team?"
        )
        return json.dumps({"text": text, "next_action": "human_handoff", "confidence": 0.4})

    paragraphs = [str(f["summary"]).strip() for f in usable]
    text = "\n\n".join(paragraphs)

    stale = any(c.get("is_stale") for f in usable for c in (f.get("citations") or []))
    if stale and audience in {"customer", "broker"}:
        text += (
            "\n\nOne of the sources behind this answer carries an effective date that has passed its "
            "review window, so it may have been updated since."
        )
    if audience == "internal":
        internal_bits = [f for f in findings if f.get("internal_only") and f.get("summary")]
        for bit in internal_bits:
            if bit["summary"] not in text:
                text += f"\n\ninternal only — {bit['summary']}"
    if audience == "contractor":
        text += (
            "\n\nThis is a record of what was logged. Any decision on payment, timeline or scope "
            "rests with the procurement team and will come from them."
        )

    next_action = next((f.get("structured", {}).get("next_action") for f in usable if f.get("structured", {}).get("next_action")), None)
    confidence = round(min(f.get("confidence", 0.7) for f in usable), 2)
    return json.dumps({"text": text, "next_action": next_action, "confidence": confidence})


def repair(variables: dict[str, Any]) -> str:
    """Best-effort JSON repair without a model: recover the largest object found."""
    raw = str(variables.get("output", ""))
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        candidate = raw[start : end + 1]
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)  # trailing commas
        candidate = candidate.replace("'", '"')
        try:
            return json.dumps(json.loads(candidate))
        except json.JSONDecodeError:
            pass
    return json.dumps({})


HANDLERS = {
    "classification": classify,
    "maintenance": maintenance,
    "property_info": property_info,
    "documentation": documentation,
    "construction_customer": construction_customer,
    "construction_internal": construction_internal,
    "contractor": contractor,
    "escalation_brief": escalation_brief,
    "repair": repair,
    "response_customer": lambda v: response_generic(v, "customer"),
    "response_broker": lambda v: response_generic(v, "broker"),
    "response_contractor": lambda v: response_generic(v, "contractor"),
    "response_internal": lambda v: response_generic(v, "internal"),
}


def generate(prompt_id: str, variables: dict[str, Any]) -> str:
    handler = HANDLERS.get(prompt_id)
    if handler is None:
        raise KeyError(
            f"offline provider has no handler for prompt {prompt_id!r}. "
            "Add one in llm/mock_provider.py, or set LLM_PROVIDER to a real provider."
        )
    return handler(variables)
