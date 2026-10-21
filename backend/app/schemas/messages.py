"""Pydantic schemas for the /api/messages endpoints.

Two surfaces:
  - User-facing: read the thread for an itinerary the user owns.
  - Agent-facing: post messages (free-text + optional structured summary
    fields), upload attachments, and read any thread.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MessageOut(BaseModel):
    """A single chat message in the thread."""

    id: UUID
    itinerary_id: UUID
    sender_user_id: UUID
    sender_role: str  # user | agent | system
    body: str
    is_summary: bool = False
    booking_id: Optional[UUID] = None
    created_at: datetime
    attachments: list["AttachmentOut"] = Field(default_factory=list)


class AttachmentOut(BaseModel):
    """Metadata for a file attached to a message."""

    id: UUID
    filename: str
    mime_type: str
    size_bytes: int
    kind: Optional[str] = None
    download_url: str  # path-style: /api/messages/attachments/{id}
    created_at: datetime


class PostMessageIn(BaseModel):
    """Body for POST /api/messages (user or agent sends a chat message)."""

    itinerary_id: UUID
    body: str = Field(min_length=1, max_length=8000)
    # The agent can tag a message as the booking summary (the card the
    # user reads to find dates + passport + visa). When True, the agent
    # MUST populate the structured ``summary_*`` fields below; they get
    # rendered as a summary card.
    is_summary: bool = False
    summary_start_date: Optional[date] = None
    summary_end_date: Optional[date] = None
    summary_destination: Optional[str] = Field(default=None, max_length=255)
    summary_passport_required: Optional[bool] = None
    summary_visa_required: Optional[bool] = None
    summary_visa_status: Optional[str] = Field(default=None, max_length=64)
    summary_notes: Optional[str] = Field(default=None, max_length=2000)


class MessageList(BaseModel):
    """List of messages in a thread, oldest first."""

    itinerary_id: UUID
    total: int
    items: list[MessageOut]


class ThreadSummary(BaseModel):
    """One chat thread (per itinerary) for the agent/admin inbox list."""

    itinerary_id: UUID
    itinerary_title: Optional[str] = None
    owner_id: UUID
    owner_email: str
    owner_name: str
    message_count: int
    first_at: Optional[datetime] = None
    last_at: Optional[datetime] = None
    last_body: Optional[str] = None
    last_sender_role: Optional[str] = None
    last_is_summary: bool = False
    queue_status: Optional[str] = None  # latest booking hand-off status, if any


class ThreadList(BaseModel):
    """Chat threads, most recently active first."""

    total: int
    items: list[ThreadSummary]


class HandOffBrief(BaseModel):
    """Short hand-off summary used by the agent to start the work.

    Built from the saved itinerary + bookings_log row when the agent
    first opens a thread. NOT stored — recomputed on each read.
    """

    itinerary_id: UUID
    user_email: str
    user_name: str
    user_nationality: Optional[str] = None
    user_passport_expiry: Optional[date] = None
    user_dob: Optional[date] = None
    itinerary_title: str
    itinerary_starts_at: Optional[datetime] = None
    itinerary_ends_at: Optional[datetime] = None
    itinerary_destination: Optional[str] = None
    hand_off_note: Optional[str] = None
    booking_status: str = "pending"
    booking_id: Optional[UUID] = None


# Resolve the forward reference (MessageOut contains AttachmentOut list)
MessageOut.model_rebuild()