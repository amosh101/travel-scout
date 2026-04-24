from pydantic import BaseModel, EmailStr, Field, HttpUrl
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
    date_flexibility: Optional[str] = "plusminus3"
    preferred_departure_date: Optional[str] = None
    preferred_return_date: Optional[str] = None


class InterestUpdate(BaseModel):
    name: Optional[str] = None
    origin_airport: Optional[str] = None
    destination_region: Optional[str] = None
    event_keywords: Optional[str] = None
    max_budget: Optional[float] = None
    notification_channels: Optional[List[str]] = None
    active: Optional[bool] = None
    date_flexibility: Optional[str] = None
    preferred_departure_date: Optional[str] = None
    preferred_return_date: Optional[str] = None


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
    date_flexibility: Optional[str]
    preferred_departure_date: Optional[date]
    preferred_return_date: Optional[date]
    created_at: datetime

    model_config = {"from_attributes": True}


# Hotel Schemas for Rich Notifications
class HotelInfo(BaseModel):
    name: str
    price_per_night: float
    image_url: Optional[str] = None
    distance_km: Optional[float] = None
    rating: Optional[float] = Field(None, ge=0, le=5)
    booking_url: Optional[str] = None
    address: Optional[str] = None


# Weather Schema
class WeatherForecast(BaseModel):
    temp_high: int
    temp_low: int
    condition: str
    humidity: int = Field(..., ge=0, le=100)
    rain_chance: int = Field(..., ge=0, le=100)


# Flight Schemas for Rich Notifications
class FlightDetails(BaseModel):
    origin: str
    destination: str
    airline: str
    price: float
    currency: str = "USD"
    depart_date: str
    return_date: Optional[str] = None
    duration_minutes: int = 0
    stops: int = 0
    airline_rating: Optional[float] = Field(None, ge=0, le=5)
    booking_url: Optional[str] = None


# Rich Itinerary Schema
class RichItinerary(BaseModel):
    trip_type: str = Field(default="leisure", pattern="^(f1|business|leisure|adventure|romance|family)$")
    flight: FlightDetails
    hotel: Optional[HotelInfo] = None
    weather: Optional[WeatherForecast] = None
    event_name: Optional[str] = None
    venue_name: Optional[str] = None
    venue_location: Optional[str] = None
    total_cost: Optional[float] = None
    savings_analysis: Optional[str] = None
    best_booking_time: Optional[str] = None
    send_packing_list: bool = True


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