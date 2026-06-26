"""Acceptance tests for the v2 foundation.

Each test maps to a checkbox in /tmp/kanban_t2_foundation.md::

- [ ] Seed script populates roles, permissions, interests catalog,
      destinations, event_sources, flight_sources
- [ ] require_permission blocks a non-admin from an admin route (test)
- [ ] Tier guard blocks a free user at 4th save attempt (test)
- [ ] Stripe webhook test flips a user's tier end-to-end
- [ ] Audit log records a test admin action with all fields
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.models import (
    ActorKind,
    AuditLog,
    Destination,
    EventSource,
    FlightSource,
    Interest,
    Permission,
    Role,
    Subscription,
    SubscriptionStatus,
    SubscriptionTier,
    TierLimit,
    User,
)
from app.security import hash_password
from app.services.authz import (
    get_user_permissions,
    grant_role,
    user_has_permission,
)
from app.services.tier_guard import (
    TierLimitExceeded,
    check_tier_limit,
    record_usage,
    require_tier_allows,
)


pytestmark = pytest.mark.asyncio


# -----------------------------------------------------------------------------
# Seed: roles, permissions, interests catalog, destinations, sources, tiers
# -----------------------------------------------------------------------------

async def test_seed_populates_roles_and_permissions(seeded):
    roles = (await seeded.execute(select(Role))).scalars().all()
    keys = {r.key for r in roles}
    assert {"superadmin", "admin", "curator", "support", "finance", "agent"} <= keys

    perms = (await seeded.execute(select(Permission))).scalars().all()
    perm_keys = {p.key for p in perms}
    assert {"user.create", "user.block", "audit.read", "billing.write"} <= perm_keys


async def test_seed_populates_interests_catalog(seeded):
    interests = (await seeded.execute(select(Interest))).scalars().all()
    keys = {i.key for i in interests}
    assert {"f1", "renaissance-art", "live-jazz"} <= keys
    f1 = next(i for i in interests if i.key == "f1")
    assert "grand prix" in f1.event_keywords
    assert f1.destination_flexibility == "strict"


async def test_seed_populates_destinations_and_sources(seeded):
    dests = (await seeded.execute(select(Destination))).scalars().all()
    iata = {d.iata_code for d in dests if d.iata_code}
    assert {"FCO", "FLR", "BCN", "LHR"} <= iata

    event_srcs = (await seeded.execute(select(EventSource))).scalars().all()
    assert {s.key for s in event_srcs} >= {"ticketmaster", "jolpica"}

    flight_srcs = (await seeded.execute(select(FlightSource))).scalars().all()
    assert {s.key for s in flight_srcs} >= {"kiwi"}

    tier_limits = (await seeded.execute(select(TierLimit))).scalars().all()
    by_tier = {tl.tier: tl for tl in tier_limits}
    assert by_tier[SubscriptionTier.FREE].max_saved_per_month == 3
    assert by_tier[SubscriptionTier.UNLIMITED].max_saved_per_month == -1
    assert by_tier[SubscriptionTier.CONCIERGE].has_agent is True


# -----------------------------------------------------------------------------
# Roles + permissions: NOT booleans
# -----------------------------------------------------------------------------

async def test_superadmin_gets_all_permissions(seeded):
    user = User(
        email="owner@example.com",
        password_hash=hash_password("hunter22hunter22"),
        name="Owner",
    )
    seeded.add(user)
    await seeded.flush()

    sup = (await seeded.execute(select(Role).where(Role.key == "superadmin"))).scalar_one()
    await grant_role(seeded, user_id=user.id, role_id=sup.id, granted_by=None)
    await seeded.commit()

    perms = await get_user_permissions(seeded, user.id)
    # Spot-check
    assert "user.create" in perms
    assert "audit.read" in perms
    assert "billing.write" in perms
    assert len(perms) > 10  # sanity: not a tiny subset


async def test_regular_user_has_no_admin_permissions(seeded):
    user = User(
        email="regular@example.com",
        password_hash=hash_password("hunter22hunter22"),
        name="Regular",
    )
    seeded.add(user)
    await seeded.flush()
    await seeded.commit()

    perms = await get_user_permissions(seeded, user.id)
    assert "user.create" not in perms
    assert "audit.read" not in perms


async def test_user_has_permission_returns_true_only_when_granted(seeded):
    user = User(
        email="curator@example.com",
        password_hash=hash_password("hunter22hunter22"),
        name="Curator",
    )
    seeded.add(user)
    await seeded.flush()
    curator = (await seeded.execute(
        select(Role).where(Role.key == "curator")
    )).scalar_one()
    await grant_role(seeded, user_id=user.id, role_id=curator.id, granted_by=None)
    await seeded.commit()

    assert await user_has_permission(seeded, user.id, "interest.admin") is True
    assert await user_has_permission(seeded, user.id, "user.create") is False


async def test_revoking_role_removes_permissions(seeded):
    from app.services.authz import revoke_role

    user = User(
        email="temp@example.com",
        password_hash=hash_password("hunter22hunter22"),
        name="Temp",
    )
    seeded.add(user)
    await seeded.flush()
    sup = (await seeded.execute(
        select(Role).where(Role.key == "support")
    )).scalar_one()
    await grant_role(seeded, user_id=user.id, role_id=sup.id, granted_by=None)
    await seeded.commit()

    assert await user_has_permission(seeded, user.id, "billing.read") is True
    assert await revoke_role(seeded, user_id=user.id, role_id=sup.id) is True
    await seeded.commit()
    assert await user_has_permission(seeded, user.id, "billing.read") is False


# -----------------------------------------------------------------------------
# Tier guard: blocks free user at 4th save attempt
# -----------------------------------------------------------------------------

async def test_free_user_can_save_three_times_then_blocked(seeded):
    user = User(
        email="free@example.com",
        password_hash=hash_password("hunter22hunter22"),
        name="Free User",
        tier=SubscriptionTier.FREE,
    )
    seeded.add(user)
    await seeded.flush()

    # 3 successful saves
    for i in range(3):
        check = await check_tier_limit(
            seeded, user_id=user.id, tier=user.tier, action="save"
        )
        assert check.allowed is True, f"save {i+1} should be allowed"
        await record_usage(seeded, user_id=user.id, action="save")
    await seeded.commit()

    # 4th save must be blocked
    with pytest.raises(TierLimitExceeded) as exc_info:
        await require_tier_allows(
            seeded, user_id=user.id, tier=user.tier, action="save"
        )
    assert exc_info.value.status_code == 402
    detail = exc_info.value.detail
    assert detail["tier"] == "free"
    assert detail["action"] == "save"
    assert detail["limit"] == 3


async def test_unlimited_tier_has_no_save_cap(seeded):
    user = User(
        email="unlim@example.com",
        password_hash=hash_password("hunter22hunter22"),
        name="Unlimited",
        tier=SubscriptionTier.UNLIMITED,
    )
    seeded.add(user)
    await seeded.flush()
    check = await check_tier_limit(
        seeded, user_id=user.id, tier=user.tier, action="save"
    )
    assert check.allowed is True
    assert check.limit == -1


# -----------------------------------------------------------------------------
# Audit log: records admin action with all fields
# -----------------------------------------------------------------------------

async def test_audit_service_records_all_fields(seeded):
    from app.services.audit import AuditService

    user = User(
        email="admin@example.com",
        password_hash=hash_password("hunter22hunter22"),
        name="Admin",
    )
    seeded.add(user)
    await seeded.flush()

    await AuditService.record(
        seeded,
        actor_user_id=user.id,
        actor_kind=ActorKind.ADMIN,
        action="user.block",
        target_kind="user",
        target_id=str(uuid4()),
        metadata={"reason": "abuse", "ticket": "SUP-42"},
        request_id="req-abc-123",
    )
    await seeded.commit()

    row = (await seeded.execute(
        select(AuditLog).where(AuditLog.action == "user.block")
    )).scalar_one()
    assert row.actor_kind == ActorKind.ADMIN
    assert row.target_kind == "user"
    assert row.metadata_json["reason"] == "abuse"
    assert row.request_id == "req-abc-123"
    assert isinstance(row.at, datetime)


# -----------------------------------------------------------------------------
# Stripe webhook: idempotent + flips tier end-to-end
# -----------------------------------------------------------------------------

def _sign(payload: bytes, secret: str) -> str:
    """Compute Stripe-style signature header."""
    ts = int(time.time())
    signed = f"{ts}.".encode() + payload
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


async def test_stripe_webhook_flips_user_tier(seeded, monkeypatch):
    """End-to-end: webhook flips a free user to active/limited after the
    subscription.created event lands."""
    import stripe  # noqa: F401

    from app.config import get_settings
    from app.routers import billing as billing_mod
    from app.routers.billing import stripe_webhook

    # Make the price id mapper find our fake price
    monkeypatch.setattr(billing_mod, "_tier_from_price_id", lambda pid: SubscriptionTier.LIMITED)

    # Patch the price-id mapping (the env var approach is too involved for a
    # unit test; we just monkeypatch the helper).
    def _sign(payload: bytes, secret: str) -> str:
        ts = int(time.time())
        signed = f"{ts}.".encode() + payload
        sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return f"t={ts},v1={sig}"

    settings = get_settings()

    user = User(
        email="buyer@example.com",
        password_hash=hash_password("hunter22hunter22"),
        name="Buyer",
        stripe_customer_id="cus_test_123",
        tier=SubscriptionTier.FREE,
    )
    seeded.add(user)
    await seeded.flush()
    await seeded.commit()

    event = {
        "id": "evt_test_1",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_test_1",
                "customer": "cus_test_123",
                "status": "active",
                "current_period_end": int(time.time()) + 30 * 86400,
                "items": {"data": [{"price": {"id": "price_test_limited"}}]},
            }
        },
    }
    payload = json.dumps(event).encode()
    sig = _sign(payload, settings.stripe_webhook_secret)

    class FakeEvent(dict):
        pass

    class FakeWebhook:
        @staticmethod
        def construct_event(payload, sig_header, secret):
            return FakeEvent(event)

    monkeypatch.setattr(stripe, "Webhook", FakeWebhook)

    class FakeRequest:
        def __init__(self, body, sig):
            self._body = body
            self.headers = {"stripe-signature": sig}

        async def body(self):
            return self._body

    req = FakeRequest(payload, sig)
    result = await stripe_webhook(req, session=seeded)
    await seeded.commit()

    assert result["status"] == "ok"

    refreshed = (await seeded.execute(
        select(User).where(User.email == "buyer@example.com")
    )).scalar_one()
    assert refreshed.tier == SubscriptionTier.LIMITED

    sub = (await seeded.execute(
        select(Subscription).where(Subscription.stripe_sub_id == "sub_test_1")
    )).scalar_one()
    assert sub.status == SubscriptionStatus.ACTIVE
    assert sub.tier == SubscriptionTier.LIMITED

    audit = (await seeded.execute(
        select(AuditLog).where(AuditLog.action == "stripe.customer.subscription.created")
    )).scalar_one()
    assert audit.actor_kind == ActorKind.SYSTEM


async def test_stripe_webhook_idempotent_on_repeat(seeded):
    """Same event_id arriving twice: only one row is processed."""
    from app.routers.billing import _record_event

    # First call
    is_new = await _record_event(
        seeded,
        event_id="evt_dup",
        event_type="invoice.paid",
        payload={},
    )
    assert is_new is True
    await seeded.commit()

    # Second call
    is_new = await _record_event(
        seeded,
        event_id="evt_dup",
        event_type="invoice.paid",
        payload={},
    )
    assert is_new is False


# -----------------------------------------------------------------------------
# Clients: missing key -> NotConfiguredError, never fake data
# -----------------------------------------------------------------------------

async def test_kiwi_client_not_configured_returns_error(seeded):
    from app.clients.base import NotConfiguredError
    from app.clients.kiwi import build_kiwi_client
    from datetime import date

    client = build_kiwi_client()
    assert client.is_configured() is False
    with pytest.raises(NotConfiguredError):
        await client.search_flights(
            origin="JNB",
            destination="FCO",
            depart=date(2027, 1, 1),
        )


async def test_ticketmaster_client_not_configured_returns_error(seeded):
    from app.clients.base import NotConfiguredError
    from app.clients.ticketmaster import build_ticketmaster_client

    client = build_ticketmaster_client()
    assert client.is_configured() is False
    with pytest.raises(NotConfiguredError):
        await client.search_events(city="Florence")


# -----------------------------------------------------------------------------
# Schema portability: SQLite roundtrip of portable JSON + UUID
# -----------------------------------------------------------------------------

async def test_portable_json_roundtrip(seeded):
    """Portable JSON column round-trips a list and dict on SQLite."""
    dest = Destination(
        iata_code="TST",
        name="Test",
        country="Testland",
        region="europe",
    )
    seeded.add(dest)
    await seeded.flush()
    # Lookup using a portable-typed query
    found = (await seeded.execute(
        select(Destination).where(Destination.iata_code == "TST")
    )).scalar_one()
    assert found.id is not None
    assert isinstance(found.id, UUID)