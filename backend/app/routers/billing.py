"""Stripe webhook handler.

Subscribes to:
- customer.subscription.created / updated / deleted
- invoice.paid / invoice.payment_failed

Idempotent via the unique ``stripe_event_id`` index on ``stripe_events``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.models import (
    ActorKind,
    StripeEvent,
    Subscription,
    SubscriptionStatus,
    SubscriptionTier,
    User,
)
from app.routers.auth import get_current_user
from app.services.audit import AuditService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])


# -----------------------------------------------------------------------------
# Tier mapping (Stripe price id -> our enum)
# -----------------------------------------------------------------------------

def _tier_from_price_id(price_id: str) -> SubscriptionTier:
    """Map a Stripe price id to a SubscriptionTier.

    The id-to-tier map is admin-managed and stored in env. For foundation we
    use placeholders; the real wiring lands with the user-journey card when
    Stripe products are created.
    """
    settings = get_settings()
    # Stub map: in production, store in env or DB. Here we hard-fail so a
    # misconfigured webhook never silently grants the wrong tier.
    mapping: dict[str, SubscriptionTier] = {}
    if hasattr(settings, "stripe_price_limited"):
        mapping[settings.stripe_price_limited] = SubscriptionTier.LIMITED
    if hasattr(settings, "stripe_price_unlimited"):
        mapping[settings.stripe_price_unlimited] = SubscriptionTier.UNLIMITED
    if hasattr(settings, "stripe_price_concierge"):
        mapping[settings.stripe_price_concierge] = SubscriptionTier.CONCIERGE
    tier = mapping.get(price_id)
    if tier is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"unknown stripe price id: {price_id!r}; cannot determine tier",
        )
    return tier


async def _user_from_customer(
    session: AsyncSession, customer_id: str
) -> User | None:
    stmt = select(User).where(User.stripe_customer_id == customer_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def _record_event(
    session: AsyncSession,
    *,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> bool:
    """Return True if newly recorded, False if already seen (idempotent)."""
    existing = await session.execute(
        select(StripeEvent).where(StripeEvent.stripe_event_id == event_id)
    )
    if existing.scalar_one_or_none() is not None:
        return False
    session.add(
        StripeEvent(
            stripe_event_id=event_id,
            event_type=event_type,
            payload=payload,
        )
    )
    await session.flush()
    return True


# -----------------------------------------------------------------------------
# Webhook endpoint
# -----------------------------------------------------------------------------

@router.post("/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    if not settings.stripe_webhook_secret or settings.stripe_webhook_secret.startswith("replace_me"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="stripe webhook not configured",
        )

    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    if not sig:
        raise HTTPException(status_code=400, detail="missing stripe-signature header")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig,
            secret=settings.stripe_webhook_secret,
        )
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid signature: {exc}") from exc

    return await _handle_event(session, event)


async def _handle_event(session: AsyncSession, event: Any) -> dict[str, Any]:
    """Process a verified Stripe event. Idempotent."""
    is_new = await _record_event(
        session,
        event_id=event["id"],
        event_type=event["type"],
        payload=dict(event),
    )
    if not is_new:
        return {"status": "duplicate", "event_id": event["id"]}

    handler = _HANDLERS.get(event["type"])
    if handler is None:
        return {"status": "ignored", "event_type": event["type"]}
    await handler(session, event["data"]["object"])

    await AuditService.record(
        session,
        actor_user_id=None,
        actor_kind=ActorKind.SYSTEM,
        action=f"stripe.{event['type']}",
        target_kind="stripe_event",
        target_id=event["id"],
    )

    await session.commit()
    return {"status": "ok", "event_id": event["id"]}


# -----------------------------------------------------------------------------
# Event handlers
# -----------------------------------------------------------------------------

async def _on_subscription_change(session: AsyncSession, sub_obj: dict[str, Any]) -> None:
    user = await _user_from_customer(session, sub_obj.get("customer"))
    if user is None:
        logger.warning("subscription event for unknown customer %s", sub_obj.get("customer"))
        return
    price_id = sub_obj["items"]["data"][0]["price"]["id"]
    tier = _tier_from_price_id(price_id)
    status_str = sub_obj.get("status", "active")
    period_end_ts = sub_obj.get("current_period_end")
    period_end = (
        datetime.fromtimestamp(period_end_ts, tz=timezone.utc)
        if period_end_ts is not None
        else None
    )
    sub_status = SubscriptionStatus(status_str)

    stmt = select(Subscription).where(Subscription.stripe_sub_id == sub_obj["id"])
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is None:
        existing = Subscription(
            user_id=user.id,
            stripe_sub_id=sub_obj["id"],
            stripe_customer_id=sub_obj["customer"],
            tier=tier,
            status=sub_status,
            current_period_end=period_end,
        )
        session.add(existing)
    else:
        existing.tier = tier
        existing.status = sub_status
        existing.current_period_end = period_end

    if sub_status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING):
        user.tier = tier


async def _on_subscription_deleted(session: AsyncSession, sub_obj: dict[str, Any]) -> None:
    user = await _user_from_customer(session, sub_obj.get("customer"))
    if user is None:
        return
    user.tier = SubscriptionTier.FREE
    stmt = select(Subscription).where(Subscription.stripe_sub_id == sub_obj["id"])
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        existing.status = SubscriptionStatus.CANCELED


async def _on_invoice_paid(session: AsyncSession, invoice_obj: dict[str, Any]) -> None:
    sub_id = invoice_obj.get("subscription")
    if not sub_id:
        return
    stmt = select(Subscription).where(Subscription.stripe_sub_id == sub_id)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None and existing.status != SubscriptionStatus.ACTIVE:
        existing.status = SubscriptionStatus.ACTIVE


async def _on_invoice_payment_failed(session: AsyncSession, invoice_obj: dict[str, Any]) -> None:
    sub_id = invoice_obj.get("subscription")
    if not sub_id:
        return
    stmt = select(Subscription).where(Subscription.stripe_sub_id == sub_id)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        existing.status = SubscriptionStatus.PAST_DUE


_HANDLERS = {
    "customer.subscription.created": _on_subscription_change,
    "customer.subscription.updated": _on_subscription_change,
    "customer.subscription.deleted": _on_subscription_deleted,
    "invoice.paid": _on_invoice_paid,
    "invoice.payment_failed": _on_invoice_payment_failed,
}


# -----------------------------------------------------------------------------
# Checkout + customer portal (2026-10-21 subscriptions)
# -----------------------------------------------------------------------------

_PRICE_BY_TIER = {
    # SubscriptionTier -> settings attribute that carries the Stripe price id.
    SubscriptionTier.LIMITED: "stripe_price_limited",
    SubscriptionTier.UNLIMITED: "stripe_price_unlimited",
    SubscriptionTier.CONCIERGE: "stripe_price_concierge",
}


@router.post("/checkout")
async def create_checkout_session(
    body: dict[str, Any] | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Start a subscription: return a hosted Stripe Checkout URL.

    PCI stays entirely on Stripe's hosted page. Honest 503 when Stripe
    keys or the tier's price id are not configured — never a fake link.
    """
    tier_name = (body or {}).get("tier", "")
    try:
        tier = SubscriptionTier(tier_name)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"unknown tier: {tier_name!r}")
    if tier == SubscriptionTier.FREE:
        raise HTTPException(status_code=400, detail="free tier needs no checkout")

    settings = get_settings()
    if not settings.stripe_secret_key or settings.stripe_secret_key.startswith("replace_me"):
        raise HTTPException(status_code=503, detail="billing not configured (stripe key)")
    attr = _PRICE_BY_TIER[tier]
    price_id = getattr(settings, attr, "")
    if not price_id:
        raise HTTPException(
            status_code=503,
            detail=f"billing not configured (price id for tier {tier_name})",
        )

    import stripe

    if user.stripe_customer_id is None:
        customer = stripe.Customer.create(
            email=user.email, name=user.name or None,
            metadata={"user_id": str(user.id)},
        )
        user.stripe_customer_id = customer.id
        await session.commit()

    checkout = stripe.checkout.Session.create(
        mode="subscription",
        customer=user.stripe_customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{settings.web_base_url}/pricing?checkout=success",
        cancel_url=f"{settings.web_base_url}/pricing",
        metadata={"user_id": str(user.id), "tier": tier.value},
    )
    await AuditService.record(
        session,
        actor_user_id=user.id,
        actor_kind=ActorKind.USER,
        action="billing.checkout_started",
        target_kind="stripe_checkout",
        target_id=checkout.id,
        metadata={"tier": tier.value},
    )
    await session.commit()
    return {"url": checkout.url, "session_id": checkout.id, "tier": tier.value}


@router.post("/portal")
async def create_portal_session(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Stripe-hosted customer portal (manage payment method / cancel)."""
    settings = get_settings()
    if not settings.stripe_secret_key or settings.stripe_secret_key.startswith("replace_me"):
        raise HTTPException(status_code=503, detail="billing not configured (stripe key)")
    if not user.stripe_customer_id:
        raise HTTPException(status_code=404, detail="no stripe customer — subscribe first")
    import stripe

    portal = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{settings.web_base_url}/pricing",
    )
    return {"url": portal.url}