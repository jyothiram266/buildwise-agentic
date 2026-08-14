"""Inbound request bodies."""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.enums import Channel, RejectionReason, ReviewAction


class Attachment(BaseModel):
    """A file reference accompanying a request (FR-INT-1).

    A reference, not the bytes: the payload lives in the DMS, and passing document
    content through this API would put KYC scans inside application logs and model
    context — exactly what FR-DOC-5 exists to prevent. The agents reason about the
    fact that a document arrived, never about its contents.
    """

    filename: str = Field(max_length=255)
    content_type: str = Field(max_length=100)
    #: DMS identifier once stored. Absent means the upload has not completed.
    dms_doc_id: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    #: What the sender says it is, used to match against the stage checklist.
    declared_type: str | None = Field(default=None, max_length=64)


class IntakeRequest(BaseModel):
    """A message arriving from any channel."""

    text: str = Field(min_length=1, max_length=8000)
    channel: Channel = Channel.WEB_CHAT
    #: Continues an existing thread. Used for the follow-up turns in the demo script.
    thread_of: str | None = None
    attachments: list[Attachment] = Field(default_factory=list, max_length=10)


class ReviewActionRequest(BaseModel):
    action: ReviewAction
    edited_text: str | None = None
    rejection_reason: RejectionReason | None = None
    assign_to: str | None = None


class TokenRequest(BaseModel):
    """Demo-only identity switch. Real deployments replace this with SSO."""

    actor_id: str
