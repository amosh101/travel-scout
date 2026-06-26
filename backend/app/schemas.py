"""Pydantic schemas (request/response DTOs)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models import ActorKind, SubscriptionStatus, SubscriptionTier


# -----------------------------------------------------------------------------
# Auth
# -----------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    tier: SubscriptionTier
    roles: list[str]


# -----------------------------------------------------------------------------
# Audit
# -----------------------------------------------------------------------------

class AuditEntry(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    actor_kind: ActorKind
    action: str
    target_kind: str | None
    target_id: str | None
    metadata: dict[str, Any]
    request_id: str | None
    at: datetime


class AuditListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AuditEntry]


# -----------------------------------------------------------------------------
# Subscription
# -----------------------------------------------------------------------------

class SubscriptionResponse(BaseModel):
    id: UUID
    user_id: UUID
    tier: SubscriptionTier
    status: SubscriptionStatus
    current_period_end: datetime | None


__all__ = [
    "AuditEntry",
    "AuditListResponse",
    "LoginRequest",
    "MeResponse",
    "RegisterRequest",
    "SubscriptionResponse",
    "TokenResponse",
]