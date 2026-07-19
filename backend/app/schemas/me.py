"""Pydantic schemas for the /me endpoint."""
from __future__ import annotations

from datetime import date
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
    """Body for PATCH /me. All fields optional. Email and tier are not updatable here."""

    model_config = {"extra": "forbid"}

    name: Optional[str] = Field(default=None, max_length=255)
    nationality: Optional[str] = Field(default=None, min_length=2, max_length=2)
    passport: Optional[str] = Field(default=None, min_length=1, max_length=32)
    dob: Optional[date] = None
    emergency_contact_name: Optional[str] = Field(default=None, max_length=255)
    emergency_contact_phone: Optional[str] = Field(default=None, max_length=32)
    home_airport: Optional[str] = Field(default=None, max_length=8)
