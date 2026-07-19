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


class OnboardingIn(BaseModel):
    """Body for POST /me/onboarding.

    The 3-step intake wizard calls this once the user finishes choosing
    their home airport, interests, and destination wishlist. ``skippable``
    is a UX escape hatch: when True the user is marked as
    ``onboarding_complete=False`` so the UI can show a "finish later" prompt
    on next login (rather than letting the wizard be permanent opt-out).
    """

    model_config = {"extra": "forbid"}

    home_airport: str = Field(min_length=3, max_length=8)
    interests: list[str] = Field(default_factory=list, max_length=64)
    destinations: list[str] = Field(default_factory=list, max_length=64)
    skippable: bool = False


class OnboardingOut(MeOut):
    """Response for POST /me/onboarding. Same shape as MeOut (re-exported
    as a distinct type so the OpenAPI schema gets a unique name and clients
    can diff the two responses if they want to)."""

    pass
