from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from datetime import datetime, date
from typing import Optional, List


# Auth Schemas
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: UUID
    email: str
    name: Optional[str]
    phone: Optional[str]
    telegram_chat_id: Optional[str]
    whatsapp_phone: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# Interest Schemas
class InterestCreate(BaseModel):
    name: str
    origin_airport: Optional[str] = None
    destination_region: Optional[str] = None
    event_keywords: Optional[str] = None
    max_budget: Optional[float] = None
    notification_channels: List[str] = ["telegram", "email"]
    active: bool = True


class InterestUpdate(BaseModel):
    name: Optional[str] = None
    origin_airport: Optional[str] = None
    destination_region: Optional[str] = None
    event_keywords: Optional[str] = None
    max_budget: Optional[float] = None
    notification_channels: Optional[List[str]] = None
    active: Optional[bool] = None


class InterestResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    origin_airport: Optional[str]
    destination_region: Optional[str]
    event_keywords: Optional[str]
    max_budget: Optional[float]
    notification_channels: List[str]
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# Alert Schemas
class FlightAlertResponse(BaseModel):
    id: UUID
    user_id: UUID
    interest_id: Optional[UUID]
    origin: str
    destination: str
    airline: Optional[str]
    price: Optional[float]
    currency: str
    depart_date: Optional[date]
    return_date: Optional[date]
    found_at: datetime
    notified: bool

    model_config = {"from_attributes": True}


class AlertDismiss(BaseModel):
    dismissed: bool = True


# Notification Schemas
class TestNotificationRequest(BaseModel):
    channel: str = Field(pattern="^(telegram|email)$")
    destination: str