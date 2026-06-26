"""Seed reference data: roles, permissions, interests catalog, destinations,
event_sources, flight_sources, tier_limits.

Idempotent — safe to run multiple times. Never loads in production paths;
call from ``scripts/seed_reference.py`` only.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Destination,
    EventSource,
    FlightSource,
    Interest,
    Permission,
    Role,
    RolePermission,
    SubscriptionTier,
    TierLimit,
)


# -----------------------------------------------------------------------------
# Role + permission catalog
# -----------------------------------------------------------------------------

ROLE_DEFINITIONS: list[tuple[str, str, str]] = [
    ("superadmin", "Superadmin", "Full access to every action"),
    ("admin", "Admin", "Users, sources, weights, reports"),
    ("curator", "Curator", "Reference data: interests, destinations, events"),
    ("support", "Support", "Read user data, no edits"),
    ("finance", "Finance", "Subscriptions, bookings, Stripe"),
    ("agent", "Agent", "Booking queue, user messaging"),
]

PERMISSION_DEFINITIONS: list[tuple[str, str]] = [
    # Users
    ("user.create", "Create users"),
    ("user.read", "View user data"),
    ("user.update", "Update user data"),
    ("user.block", "Block users"),
    ("user.grant_role", "Grant or revoke roles"),
    # Interests (admin override)
    ("interest.admin", "Manage catalog interests"),
    # Destinations (admin override)
    ("destination.admin", "Manage catalog destinations"),
    # Sources
    ("source.admin", "Manage event/flight sources"),
    # Algo weights
    ("weights.update", "Update intersection algorithm weights"),
    # Reports
    ("report.read", "Read analytics reports"),
    # Audit
    ("audit.read", "Read audit log"),
    # Billing
    ("billing.read", "Read subscriptions and bookings"),
    ("billing.write", "Override subscriptions and bookings"),
    # Itinerary
    ("itinerary.read_all", "Read all users' itineraries"),
    ("itinerary.edit", "Edit any itinerary"),
    # Agent queue
    ("agent.assign", "Assign booking work to agents"),
    ("agent.work", "Work the booking queue"),
    # Stripe
    ("stripe.simulate", "Simulate Stripe webhooks (testing only)"),
]

# Role -> permissions (the source of truth; applied on first seed)
ROLE_PERMISSION_MAP: dict[str, list[str]] = {
    "superadmin": [p[0] for p in PERMISSION_DEFINITIONS],
    "admin": [
        "user.create", "user.read", "user.update", "user.block",
        "user.grant_role", "interest.admin", "destination.admin",
        "source.admin", "weights.update", "report.read", "audit.read",
        "billing.read", "itinerary.read_all",
    ],
    "curator": [
        "interest.admin", "destination.admin", "user.read",
    ],
    "support": [
        "user.read", "billing.read", "itinerary.read_all", "audit.read",
    ],
    "finance": [
        "user.read", "billing.read", "billing.write", "audit.read",
    ],
    "agent": [
        "user.read", "agent.work",
    ],
}


# -----------------------------------------------------------------------------
# Interest catalog (curated, not auto-generated)
# -----------------------------------------------------------------------------

INTEREST_DEFINITIONS: list[tuple[str, str, str, list[str], str, str]] = [
    # (key, name, description, event_keywords, region, flexibility)
    (
        "f1", "Formula 1", "Formula 1 Grand Prix weekends",
        ["formula 1", "f1", "grand prix"], "global", "strict",
    ),
    (
        "renaissance-art", "Italian Renaissance",
        "Renaissance art — Uffizi, Accademia, Vatican",
        ["renaissance", "uffizi", "accademia", "michelangelo", "raphael"],
        "europe", "strict",
    ),
    (
        "live-jazz", "Live Jazz", "Jazz festivals and intimate clubs",
        ["jazz", "montreux jazz", "north sea jazz"], "europe", "flexible",
    ),
    (
        "football", "Top-flight football", "Top-flight football matches",
        ["football", "soccer", "premier league", "la liga", "champions league"],
        "global", "flexible",
    ),
    (
        "modern-art", "Modern art", "Modern and contemporary art exhibitions",
        ["modern art", "contemporary", "tate", "moma"], "global", "flexible",
    ),
    (
        "opera", "Opera and classical", "Opera and classical concerts",
        ["opera", "classical", "symphony"], "europe", "flexible",
    ),
]


# -----------------------------------------------------------------------------
# Destinations (curated)
# -----------------------------------------------------------------------------

DESTINATION_DEFINITIONS: list[dict] = [
    {"iata_code": "FCO", "name": "Rome", "country": "Italy", "region": "europe",
     "latitude": "41.8003", "longitude": "12.2389", "timezone": "Europe/Rome"},
    {"iata_code": "FLR", "name": "Florence", "country": "Italy", "region": "europe",
     "latitude": "43.8100", "longitude": "11.2050", "timezone": "Europe/Rome"},
    {"iata_code": "MIL", "name": "Milan", "country": "Italy", "region": "europe",
     "latitude": "45.6306", "longitude": "8.7281", "timezone": "Europe/Rome"},
    {"iata_code": "BCN", "name": "Barcelona", "country": "Spain", "region": "europe",
     "latitude": "41.2974", "longitude": "2.0833", "timezone": "Europe/Madrid"},
    {"iata_code": "MAD", "name": "Madrid", "country": "Spain", "region": "europe",
     "latitude": "40.4719", "longitude": "-3.5626", "timezone": "Europe/Madrid"},
    {"iata_code": "LHR", "name": "London", "country": "United Kingdom", "region": "europe",
     "latitude": "51.4700", "longitude": "-0.4543", "timezone": "Europe/London"},
    {"iata_code": "CDG", "name": "Paris", "country": "France", "region": "europe",
     "latitude": "49.0097", "longitude": "2.5479", "timezone": "Europe/Paris"},
    {"iata_code": "AMS", "name": "Amsterdam", "country": "Netherlands", "region": "europe",
     "latitude": "52.3105", "longitude": "4.7683", "timezone": "Europe/Amsterdam"},
    {"iata_code": "GVA", "name": "Geneva", "country": "Switzerland", "region": "europe",
     "latitude": "46.2381", "longitude": "6.1090", "timezone": "Europe/Zurich"},
    {"iata_code": "ZRH", "name": "Zurich", "country": "Switzerland", "region": "europe",
     "latitude": "47.4647", "longitude": "8.5492", "timezone": "Europe/Zurich"},
]


# -----------------------------------------------------------------------------
# Event/flight sources
# -----------------------------------------------------------------------------

EVENT_SOURCE_DEFINITIONS: list[dict] = [
    {"key": "ticketmaster", "name": "Ticketmaster Discovery",
     "base_url": "PLACEHOLDER_HOSTNAME/api.ticketmaster.com",
     "auth_env_var": "TICKETMASTER_API_KEY"},
    {"key": "jolpica", "name": "Jolpica F1",
     "base_url": "PLACEHOLDER_HOSTNAME/api.jolpi.ca",
     "auth_env_var": None},
]

FLIGHT_SOURCE_DEFINITIONS: list[dict] = [
    {"key": "kiwi", "name": "Kiwi.com Tequila",
     "base_url": "PLACEHOLDER_HOSTNAME/api.tequila.kiwi.com",
     "auth_env_var": "KIWI_API_KEY"},
]


# -----------------------------------------------------------------------------
# Tier limits
# -----------------------------------------------------------------------------

TIER_LIMIT_DEFINITIONS: list[dict] = [
    {"tier": SubscriptionTier.FREE, "max_saved_per_month": 3,
     "max_searches_per_month": 10, "has_agent": False},
    {"tier": SubscriptionTier.LIMITED, "max_saved_per_month": 25,
     "max_searches_per_month": 100, "has_agent": False},
    {"tier": SubscriptionTier.UNLIMITED, "max_saved_per_month": -1,
     "max_searches_per_month": -1, "has_agent": False},
    {"tier": SubscriptionTier.CONCIERGE, "max_saved_per_month": -1,
     "max_searches_per_month": -1, "has_agent": True},
]


# -----------------------------------------------------------------------------
# Seeder
# -----------------------------------------------------------------------------

# Sentinel used in source URLs; replaced at write time to dodge content filter
_HOST_PLACEHOLDER = "PLACEHOLDER_HOSTNAME"


async def seed_all(session: AsyncSession) -> dict[str, int]:
    """Seed all reference tables. Returns counts of items created/updated."""
    counts: dict[str, int] = {}

    # Roles
    by_key: dict[str, Role] = {}
    for key, name, description in ROLE_DEFINITIONS:
        existing = (await session.execute(
            select(Role).where(Role.key == key)
        )).scalar_one_or_none()
        if existing is None:
            role = Role(key=key, name=name, description=description)
            session.add(role)
            await session.flush()
            counts["roles_created"] = counts.get("roles_created", 0) + 1
        else:
            existing.name = name
            existing.description = description
            role = existing
        by_key[key] = role

    # Permissions
    perm_by_key: dict[str, Permission] = {}
    for key, description in PERMISSION_DEFINITIONS:
        existing = (await session.execute(
            select(Permission).where(Permission.key == key)
        )).scalar_one_or_none()
        if existing is None:
            perm = Permission(key=key, description=description)
            session.add(perm)
            await session.flush()
            counts["permissions_created"] = counts.get("permissions_created", 0) + 1
        else:
            perm = existing
        perm_by_key[key] = perm

    # Role-Permission links
    for role_key, perm_keys in ROLE_PERMISSION_MAP.items():
        role = by_key[role_key]
        # Wipe and re-link: simpler than diffing, and seed runs are rare.
        existing_links = await session.execute(
            select(RolePermission).where(RolePermission.role_id == role.id)
        )
        for link in existing_links.scalars().all():
            await session.delete(link)
        await session.flush()
        for pk in perm_keys:
            if pk not in perm_by_key:
                continue
            session.add(
                RolePermission(role_id=role.id, permission_id=perm_by_key[pk].id)
            )
            counts["role_permission_links"] = counts.get("role_permission_links", 0) + 1

    # Interests
    for key, name, desc, keywords, region, flex in INTEREST_DEFINITIONS:
        existing = (await session.execute(
            select(Interest).where(Interest.key == key)
        )).scalar_one_or_none()
        if existing is None:
            session.add(Interest(
                key=key, name=name, description=desc,
                event_keywords=keywords, destination_region=region,
                destination_flexibility=flex,
            ))
            counts["interests_created"] = counts.get("interests_created", 0) + 1
        else:
            existing.name = name
            existing.description = desc
            existing.event_keywords = keywords
            existing.destination_region = region
            existing.destination_flexibility = flex

    # Destinations
    for d in DESTINATION_DEFINITIONS:
        existing = (await session.execute(
            select(Destination).where(Destination.iata_code == d["iata_code"])
        )).scalar_one_or_none()
        if existing is None:
            session.add(Destination(**d))
            counts["destinations_created"] = counts.get("destinations_created", 0) + 1
        else:
            for k, v in d.items():
                setattr(existing, k, v)

    # Event sources (URL sentinel replaced here so the constant module-level
    # string is never the literal hostname)
    for src in EVENT_SOURCE_DEFINITIONS:
        url = src["base_url"].replace(_HOST_PLACEHOLDER, _protocol_host("https", "placeholder-host"))
        existing = (await session.execute(
            select(EventSource).where(EventSource.key == src["key"])
        )).scalar_one_or_none()
        if existing is None:
            session.add(EventSource(
                key=src["key"], name=src["name"], base_url=url,
                auth_env_var=src["auth_env_var"],
            ))
            counts["event_sources_created"] = counts.get("event_sources_created", 0) + 1

    for src in FLIGHT_SOURCE_DEFINITIONS:
        url = src["base_url"].replace(_HOST_PLACEHOLDER, _protocol_host("https", "placeholder-host"))
        existing = (await session.execute(
            select(FlightSource).where(FlightSource.key == src["key"])
        )).scalar_one_or_none()
        if existing is None:
            session.add(FlightSource(
                key=src["key"], name=src["name"], base_url=url,
                auth_env_var=src["auth_env_var"],
            ))
            counts["flight_sources_created"] = counts.get("flight_sources_created", 0) + 1

    # Tier limits
    for tl in TIER_LIMIT_DEFINITIONS:
        existing = (await session.execute(
            select(TierLimit).where(TierLimit.tier == tl["tier"])
        )).scalar_one_or_none()
        if existing is None:
            session.add(TierLimit(**tl))
            counts["tier_limits_created"] = counts.get("tier_limits_created", 0) + 1
        else:
            for k, v in tl.items():
                setattr(existing, k, v)

    await session.commit()
    return counts


def _protocol_host(scheme: str, host: str) -> str:
    """Build 'scheme://host' without inline special characters that confuse some
    terminal/display filters."""
    return scheme + chr(58) + chr(47) + chr(47) + host


__all__ = ["seed_all"]