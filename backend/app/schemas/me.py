"""Pydantic schemas for the /me endpoint."""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class MeOut(BaseModel):
    """Response shape for GET /me."""

    id: UUID
    email: EmailStr
    name: Optional[str] = None
    tier: str
    next_billing_date: Optional[str] = None
    home_airport: Optional[str] = None
    onboarding_complete: bool = False
    role: str = "user"


class MePatch(BaseModel):
    """Stub for the next card (PATCH /me). All fields optional."""

    name: Optional[str] = Field(default=None, max_length=255)
    home_airport: Optional[str] = Field(default=None, max_length=8)
    onboarding_complete: Optional[bool] = None
