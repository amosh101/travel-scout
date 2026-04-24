from sqlalchemy import Column, String, Boolean, DateTime, Date, Numeric, Text, ARRAY, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(Text, unique=True, nullable=False, index=True)
    password_hash = Column(Text, nullable=False)
    name = Column(String(255))
    phone = Column(String(50))
    telegram_chat_id = Column(String(50))
    whatsapp_phone = Column(String(50))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    interests = relationship("Interest", back_populates="user", cascade="all, delete-orphan")
    alerts = relationship("FlightAlert", back_populates="user", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="user", uselist=False)


class Interest(Base):
    __tablename__ = "interests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    origin_airport = Column(String(10))
    destination_region = Column(String(100))
    event_keywords = Column(Text)
    max_budget = Column(Numeric(10, 2))
    notification_channels = Column(ARRAY(String), default=list)
    active = Column(Boolean, default=True)
    date_flexibility = Column(String(20), default="plusminus3")  # exact, plusminus1, plusminus3, plusminus7, weekends
    preferred_departure_date = Column(Date)
    preferred_return_date = Column(Date)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    user = relationship("User", back_populates="interests")
    alerts = relationship("FlightAlert", back_populates="interest")


class FlightAlert(Base):
    __tablename__ = "flight_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    interest_id = Column(UUID(as_uuid=True), ForeignKey("interests.id", ondelete="SET NULL"))
    origin = Column(String(10), nullable=False)
    destination = Column(String(10), nullable=False)
    airline = Column(String(100))
    price = Column(Numeric(10, 2))
    currency = Column(String(3), default="USD")
    depart_date = Column(Date)
    return_date = Column(Date)
    found_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    notified = Column(Boolean, default=False)

    user = relationship("User", back_populates="alerts")
    interest = relationship("Interest", back_populates="alerts")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan = Column(String(50), default="free")
    status = Column(String(50), default="active")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    user = relationship("User", back_populates="subscription")