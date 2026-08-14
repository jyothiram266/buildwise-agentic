"""Typed exception hierarchy.

Every failure the system can produce is one of these, so the graph's failure
table (architecture Section 3.4) can branch on type rather than on string
matching. A bare `Exception` escaping a module is a bug: it becomes an
unclassified human-triage case with no useful context.
"""

from __future__ import annotations


class BuildWiseError(Exception):
    """Base for every error this system raises deliberately."""

    def __init__(self, message: str, *, case_id: str | None = None, **context: object) -> None:
        super().__init__(message)
        self.message = message
        self.case_id = case_id
        self.context = context

    def to_dict(self) -> dict[str, object]:
        return {
            "error": type(self).__name__,
            "message": self.message,
            "case_id": self.case_id,
            **{k: str(v) for k, v in self.context.items()},
        }


class InsufficientDataError(BuildWiseError):
    """Required grounding is absent. Refuse; never substitute a guess."""


class ScopeViolationError(BuildWiseError):
    """An attempt to read or widen beyond the caller's AccessScope."""


class ConnectorError(BuildWiseError):
    """A system of record failed, timed out, or returned an unusable payload."""


class ValidationFailure(BuildWiseError):
    """Model output failed schema validation after the single repair attempt."""


class ApprovalRequiredError(BuildWiseError):
    """A tier-2+ write was attempted without a valid ApprovalToken."""


class PolicyViolationError(BuildWiseError):
    """A code path tried to do something the autonomy policy forbids outright."""


class ConfigurationError(BuildWiseError):
    """Missing or contradictory configuration. Raised at startup, not per request."""
