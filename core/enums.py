"""Canonical enumerations.

AGENTS.md Section 5 freezes the first six enums in this module. They are the
vocabulary every other module speaks; nothing below the API layer is allowed to
invent a parallel set of strings for the same concept, because a stringly-typed
intent is exactly how a routing table silently stops matching reality.

Enums added after Section 5 (maintenance categories, booking stages, escalation
types...) are domain vocabulary drawn from the PRD. They live here for the same
reason: one definition, imported everywhere.
"""

from __future__ import annotations

from enum import Enum


class Intent(str, Enum):
    """The 9-class taxonomy from PRD FR-INT-3."""

    SALES_INQUIRY = "SALES_INQUIRY"
    BOOKING = "BOOKING"
    DOCUMENTATION = "DOCUMENTATION"
    PAYMENT = "PAYMENT"
    CONSTRUCTION_STATUS = "CONSTRUCTION_STATUS"
    MAINTENANCE = "MAINTENANCE"
    CONTRACTOR_UPDATE = "CONTRACTOR_UPDATE"
    COMPLAINT_ESCALATION = "COMPLAINT_ESCALATION"
    OTHER = "OTHER"


class Role(str, Enum):
    """Actor roles from architecture Section 6.1."""

    PUBLIC_LEAD = "public_lead"
    CUSTOMER = "customer"
    RESIDENT = "resident"
    BROKER = "broker"
    CONTRACTOR = "contractor"
    SALES_STAFF = "sales_staff"
    SITE_ENGINEER = "site_engineer"
    LEGAL_FINANCE = "legal_finance"
    MANAGER = "manager"


class RiskTier(int, Enum):
    """PRD Section 9. Ordering is meaningful: higher int == less autonomy."""

    AUTO = 0  # auto-send
    AUTO_NOTIFY = 1  # auto-send + notify owning team
    DRAFT_APPROVAL = 2  # human approves before send
    ESCALATE_ONLY = 3  # acknowledgement only, human owns


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class Channel(str, Enum):
    WEB_CHAT = "web_chat"
    EMAIL = "email"
    FORM = "form"
    CALL_TRANSCRIPT = "call_transcript"
    INTERNAL_PORTAL = "internal_portal"
    CONTRACTOR_PORTAL = "contractor_portal"


# --------------------------------------------------------------------------
# Domain vocabulary (post-Section-5 additions)
# --------------------------------------------------------------------------


class MaintenanceCategory(str, Enum):
    """PRD FR-MNT-1. Exactly nine categories; the eval gate counts against these."""

    PLUMBING = "plumbing"
    ELECTRICAL = "electrical"
    CIVIL = "civil"
    LIFT = "lift"
    COMMON_AREA = "common_area"
    PARKING = "parking"
    WATER_SUPPLY = "water_supply"
    SECURITY = "security"
    WARRANTY_CLAIM = "warranty_claim"


#: Hazard classes that bypass normal routing entirely (PRD FR-MNT-4). These are
#: severity signals rather than categories, so they are kept separate from
#: MaintenanceCategory and detected by keyword in deterministic code.
SAFETY_CRITICAL_SIGNALS = (
    "gas_leak",
    "electrical_hazard",
    "structural_crack",
    "lift_entrapment",
)


class BookingStage(str, Enum):
    """Ordered lifecycle. `order()` drives stage-appropriate checklists."""

    KYC_PENDING = "kyc_pending"
    BOOKED = "booked"
    AGREEMENT = "agreement"
    REGISTERED = "registered"
    LOAN_DISBURSED = "loan_disbursed"
    POSSESSION_TAKEN = "possession_taken"

    @property
    def order(self) -> int:
        return list(BookingStage).index(self)


class UnitStatus(str, Enum):
    AVAILABLE = "available"
    HELD = "held"
    BOOKED = "booked"
    SOLD = "sold"


class DocumentStatus(str, Enum):
    SUBMITTED = "submitted"
    PENDING = "pending"
    EXPIRED = "expired"


class PaymentStatus(str, Enum):
    PAID = "paid"
    DUE = "due"
    OVERDUE = "overdue"


class TicketStatus(str, Enum):
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class BlockerCategory(str, Enum):
    MATERIAL_SHORTAGE = "material_shortage"
    MANPOWER = "manpower"
    APPROVAL_DELAY = "approval_delay"
    WEATHER = "weather"
    VENDOR_PAYMENT_DISPUTE = "vendor_payment_dispute"
    EQUIPMENT = "equipment"


class EscalationType(str, Enum):
    """Escalation taxonomy; maps to owner team + SLA in the routing matrix."""

    REFUND_DEMAND = "refund_demand"
    LEGAL_NOTICE = "legal_notice"
    PAYMENT_DISPUTE = "payment_dispute"
    SAFETY_INCIDENT = "safety_incident"
    STRUCTURAL_DEFECT = "structural_defect"
    DISCOUNT_REQUEST = "discount_request"
    REGULATORY_COMPLAINT = "regulatory_complaint"
    MEDIA_THREAT = "media_threat"
    POSSESSION_DATE_DISPUTE = "possession_date_dispute"
    REPEATED_CONTACT = "repeated_contact"
    LOW_CONFIDENCE = "low_confidence"
    SOURCE_CONFLICT = "source_conflict"
    MISSING_DATA = "missing_data"
    CONTRACTOR_COMMITMENT = "contractor_commitment"


class Collection(str, Enum):
    """Corpus collections from architecture Section 4.1."""

    PROPERTY_CATALOG = "property_catalog"
    PRICING_SHEETS = "pricing_sheets"
    PROJECT_REPORTS = "project_reports"
    DOC_CHECKLISTS = "doc_checklists"
    POLICIES = "policies"
    FAQ = "faq"


class CaseStatus(str, Enum):
    OPEN = "open"
    AWAITING_APPROVAL = "awaiting_approval"
    ESCALATED = "escalated"
    ANSWERED = "answered"
    HUMAN_TRIAGE = "human_triage"
    REJECTED = "rejected"
    #: The pipeline raised and the case was handed to a human. Distinct from
    #: HUMAN_TRIAGE, which is a routing decision rather than a fault.
    FAILED = "failed"
    CLOSED = "closed"


class ReviewAction(str, Enum):
    APPROVE = "approve"
    EDIT_AND_SEND = "edit_and_send"
    REJECT = "reject"
    REASSIGN = "reassign"


class RejectionReason(str, Enum):
    """Enumerated so overrides become eval-backlog data, not free text."""

    FACTUALLY_WRONG = "factually_wrong"
    MISSING_CONTEXT = "missing_context"
    WRONG_TONE = "wrong_tone"
    TOO_MUCH_DISCLOSURE = "too_much_disclosure"
    NOT_ENOUGH_DETAIL = "not_enough_detail"
    WRONG_OWNER = "wrong_owner"
    POLICY_VIOLATION = "policy_violation"
    CITATION_INADEQUATE = "citation_inadequate"


#: Roles that receive customer-safe disclosure only. Used by the response agent
#: and the risk engine; a single source of truth prevents the two drifting apart.
EXTERNAL_ROLES = frozenset(
    {Role.PUBLIC_LEAD, Role.CUSTOMER, Role.RESIDENT, Role.BROKER, Role.CONTRACTOR}
)

#: Roles allowed to approve a tier-2 draft or own a tier-3 escalation.
APPROVER_ROLES = frozenset({Role.MANAGER, Role.LEGAL_FINANCE, Role.SITE_ENGINEER})
