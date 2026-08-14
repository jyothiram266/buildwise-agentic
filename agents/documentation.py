"""Documentation agent.

Compares the checklist for the booking's current stage against what the DMS
actually holds, and reports the gap. Two rules shape the implementation:

* **The diff is computed in code.** Asking a model which documents are missing
  invites it to name a plausible document that is not on the checklist. Here the
  set arithmetic happens in python and the model only writes the sentence around
  the result.
* **Expired is a gap, not a submission.** The distinction matters commercially — a
  customer told "already submitted" about an expired bank sanction letter will
  arrive at registration unable to proceed.

The agent gives procedural guidance only. Interpreting a clause is a legal
question and routes to legal (PRD FR-DOC-4).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from connectors import registry
from connectors.crm import BookingQuery
from connectors.dms import DocumentQuery
from core.enums import Collection
from core.errors import InsufficientDataError
from core.models import AgentFinding
from governance.policy_registry import get_registry
from orchestration.state import CaseState

from agents.base import BaseAgent

LEGAL_INTERPRETATION_SIGNALS = (
    "what does clause", "what does this clause", "clause mean", "legally", "legal implication",
    "am i liable", "who is liable", "interpret", "is this enforceable", "my rights",
    "can they charge me", "as per law", "under rera", "stamp duty liability",
)

def _checklist_policy() -> dict:
    """The authoritative stage checklist, from the versioned policy file."""
    return get_registry().policy("document_checklists")


#: The canonical booking stages, in order. A customer can ask about a later stage
#: ("what do I need for registration") while sitting at an earlier one, and the
#: honest answer is what is outstanding *now*, because you cannot be missing
#: registration paperwork before you reach registration.
STAGE_ORDER = [
    "kyc_pending", "booked", "agreement", "registered", "loan_disbursed", "possession_taken",
]  # mirrors document_checklists.yaml stage_order; asserted in tests/unit

#: How people say it -> what the records call it. "registration" is not a stage
#: name; "registered" is. Without this mapping the DMS was queried for a stage that
#: does not exist, returned nothing, and the agent reported nothing outstanding —
#: telling a customer with three open items that they were complete.
STAGE_ALIASES = {
    "kyc": "kyc_pending", "kyc pending": "kyc_pending",
    "booking": "booked", "booked": "booked",
    "agreement": "agreement", "sale agreement": "agreement",
    "registration": "registered", "registered": "registered", "registry": "registered",
    "loan": "loan_disbursed", "disbursement": "loan_disbursed",
    "possession": "possession_taken", "handover": "possession_taken",
}

STAGE_LABELS = {
    "enquiry": "enquiry",
    "booking": "booking",
    "agreement": "agreement",
    "registration": "registration",
    "possession": "possession",
    "possession_taken": "post-possession",
}


class DocumentationOutput(BaseModel):
    summary: str
    next_action: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class DocumentationAgent(BaseAgent):
    name = "documentation"
    prompt_id = "documentation"
    collections = [Collection.DOC_CHECKLISTS.value, Collection.POLICIES.value, Collection.FAQ.value]

    async def _run(self, state: CaseState) -> AgentFinding:
        entities = state.classification.entities if state.classification else {}
        booking_id = entities.get("booking_id") or (
            state.scope.booking_ids[0] if state.scope.booking_ids else None
        )
        if not booking_id:
            raise InsufficientDataError(
                "No booking is associated with this request, so there is no document checklist to "
                "compare against. A booking reference is needed before this can be answered."
            )

        booking_result = await registry.crm().query_booking(
            BookingQuery(booking_id=booking_id), state.scope
        )
        if not booking_result.found:
            raise InsufficientDataError(
                f"Booking {booking_id} is not visible to this actor, so no document status can be "
                "reported."
            )
        booking = booking_result.bookings[0]

        # The requested stage may be ahead of the current one, which is a normal
        # question and not a reason to report an empty checklist.
        requested = self._requested_stage(state.masked_input)
        target_stage = self._effective_stage(requested, booking.stage)
        looking_ahead = bool(requested and requested != target_stage)
        documents = await registry.dms().query_documents(
            DocumentQuery(booking_id=booking_id, stage=target_stage), state.scope
        )

        # The requirement list comes from policy, not from a retrieved chunk.
        # Retrieval still runs, but only to cite the published wording a customer can
        # be pointed at — the arithmetic never depends on a search result.
        chunks = await self.retrieve(state, f"{target_stage} stage document checklist")
        required = self._required_for_stage(target_stage)
        if not required:
            # Refusing rather than falling back to "whatever the DMS happens to hold".
            # That fallback can only ever report documents that exist, so it can never
            # report a missing one — it produced a confident "nothing is pending" for a
            # customer with two pending items and one expired. An unparsed checklist is
            # missing data, and missing data is an escalation (design rule #1).
            raise InsufficientDataError(
                f"No document checklist is defined for the "
                f"{STAGE_LABELS.get(target_stage, target_stage)} stage, so the outstanding list "
                "cannot be computed. Reporting nothing outstanding would be worse than reporting "
                "nothing at all."
            )

        held = {d.type: d for d in documents.documents}
        submitted = [t for t in required if t in held and held[t].status == "submitted"]
        expired = [t for t in required if t in held and held[t].status == "expired"]
        missing = [t for t in required if t not in held or held[t].status == "pending"]

        facts = {
            "booking_id": booking_id,
            "stage": target_stage,
            "stage_label": STAGE_LABELS.get(target_stage, target_stage),
            "current_stage": booking.stage,
            "required": required,
            "submitted": submitted,
            "missing": missing,
            "expired": expired,
            "expiring_soon": [
                {"type": d.type, "days_to_expiry": d.days_to_expiry}
                for d in documents.documents
                if d.days_to_expiry is not None and 0 <= d.days_to_expiry <= 30
            ],
            "looking_ahead_to": requested if looking_ahead else None,
            "clause_interpretation_requested": any(
                signal in state.masked_input.lower() for signal in LEGAL_INTERPRETATION_SIGNALS
            ),
            "where_to_submit": (
                "Documents go to the documentation desk at the site office or through the customer "
                "portal, whichever you prefer."
            ),
        }

        output = await self.generate(
            state,
            {"facts": facts, "context": self.context_block(chunks), "request": state.masked_input},
            DocumentationOutput,
        )
        assert isinstance(output, DocumentationOutput)

        # FR-DOC-3: a reminder draft, never a sent reminder. Composed in code from
        # the computed gap rather than generated, because a reminder that names a
        # document not on the checklist sends a customer looking for paperwork that
        # does not exist. Sending is a separate, human-approved step.
        reminder = self._reminder_draft(booking, target_stage, missing, expired, facts)

        return AgentFinding(
            agent=self.name,
            status="ok",
            summary=output.summary,
            structured={
                "booking_id": booking_id,
                "reminder_draft": reminder,
                "reminder_sent": False,
                "stage": target_stage,
                "missing": missing,
                "expired": expired,
                "submitted_count": len(submitted),
                "required_count": len(required),
                "gap_count": len(missing) + len(expired),
                "legal_referral": facts["clause_interpretation_requested"],
                "next_action": output.next_action,
            },
            citations=self.citations_from(chunks),
            confidence=output.confidence,
        )

    @staticmethod
    def _reminder_draft(booking, stage: str, missing: list[str], expired: list[str], facts: dict) -> str | None:
        """Draft a reminder for outstanding documents, or None when nothing is due."""
        if not missing and not expired:
            return None

        def label(doc_type: str) -> str:
            return DocumentationAgent._label_for(doc_type)

        lines = [
            f"Dear {booking.customer_name},",
            "",
            f"A quick note on the paperwork for {booking.project_name} "
            f"{booking.tower_name}, unit {booking.unit_id}. To complete the "
            f"{STAGE_LABELS.get(stage, stage)} stage we still need the following from you:",
            "",
        ]
        lines += [f"  - {label(item)}" for item in missing]
        if expired:
            lines.append("")
            lines.append(
                "These are on file but have passed their validity date, so a current copy is "
                "needed:"
            )
            lines += [f"  - {label(item)}" for item in expired]
        lines += [
            "",
            facts["where_to_submit"],
            "",
            "If any of these are already on their way to us, please ignore this note — it "
            "means they had not been logged when this was written.",
        ]
        return "\n".join(lines)

    @staticmethod
    def _requested_stage(text: str) -> str | None:
        """Canonical stage named in the request, if any."""
        low = text.lower()
        # Longest alias first so "kyc pending" wins over "kyc".
        for alias in sorted(STAGE_ALIASES, key=len, reverse=True):
            if alias in low:
                return STAGE_ALIASES[alias]
        return None

    @staticmethod
    def _effective_stage(requested: str | None, current: str) -> str:
        """Clamp a forward-looking question back to the stage actually in progress."""
        if requested is None:
            return current
        try:
            if STAGE_ORDER.index(requested) > STAGE_ORDER.index(current):
                return current
        except ValueError:
            return current
        return requested

    @staticmethod
    def _required_for_stage(stage: str) -> list[str]:
        """Required document types for a stage, straight from the policy file."""
        spec = _checklist_policy().get("stages", {}).get(stage)
        if not spec:
            return []
        return [d["type"] for d in spec.get("documents", [])]

    @staticmethod
    def _label_for(doc_type: str) -> str:
        """Customer-facing wording for a document type, also from the policy."""
        for spec in _checklist_policy().get("stages", {}).values():
            for doc in spec.get("documents", []):
                if doc["type"] == doc_type:
                    return str(doc.get("label", doc_type.replace("_", " ")))
        return doc_type.replace("_", " ")

    @staticmethod
    def _required_from_checklist(chunks: list, stage: str) -> list[str]:
        """Pull the required document types out of the retrieved checklist.

        The corpus renders checklists as a markdown table with a machine-readable
        `Type` column carrying the canonical snake_case identifier — the same value
        the DMS stores. That column exists precisely so this parse does not have to
        guess: matching prose like "Stamp duty payment receipt" against the type
        `stamp_duty_receipt` is the kind of fuzzy mapping that fails silently and
        produces a wrong answer rather than an error.
        """
        import re

        found: list[str] = []
        for chunk in chunks:
            if chunk.collection.value != Collection.DOC_CHECKLISTS.value:
                continue
            haystack = f"{chunk.content}\n{chunk.section_heading or ''}".lower()
            if stage not in haystack and stage.replace("_", " ") not in haystack:
                continue
            for line in chunk.content.splitlines():
                if not line.strip().startswith("|"):
                    continue
                cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
                for cell in cells:
                    if re.fullmatch(r"[a-z][a-z0-9_]{3,}", cell) and cell not in found:
                        found.append(cell)
        return found
