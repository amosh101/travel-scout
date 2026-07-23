"""Tests for GET /api/profile/me/export (GDPR JSON dump).

The endpoint is mounted on the existing /profile router (per task hard rule:
only touch profile.py), so the effective path is /api/profile/me/export.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# Per-test SQLite file so each test gets a clean schema.
TEST_DB_FILE = f"./test_me_export_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_FILE}"
os.environ["DATABASE_URL_SYNC"] = f"sqlite:///{TEST_DB_FILE}"

from app.config import get_settings  # noqa: E402
from app.database import Base, dispose_engine  # noqa: E402
from app.main import create_app  # noqa: E402
import app.models  # noqa: E402,F401  -- registers models on Base.metadata
from app.models import AuditLog, SavedItinerary  # noqa: E402
from app.routers.profile import INTEREST_CATALOG  # noqa: E402


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    get_settings.cache_clear()
    await dispose_engine()
    from app.database import get_engine as _get_engine

    eng = _get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac
        await dispose_engine()
    try:
        os.remove(TEST_DB_FILE)
    except FileNotFoundError:
        pass


async def _register_and_login(client: AsyncClient, email: str, password: str) -> str:
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": "Export User"},
    )
    assert r.status_code in (200, 201), r.text
    r = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_export_requires_auth(client):
    r = await client.get("/api/profile/me/export")
    assert r.status_code == 401


async def test_export_returns_user_record(client):
    email = "export-user@example.com"
    token = await _register_and_login(client, email, "supersecret1")
    r = await client.get(
        "/api/profile/me/export",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert "attachment" in r.headers.get("content-disposition", "")
    body = r.json()
    assert body["profile"]["email"] == email
    assert "id" in body["profile"]
    assert "name" in body["profile"]
    assert "tier" in body["profile"]
    assert isinstance(body["itineraries"], list)
    assert isinstance(body["messages"], list)
    assert isinstance(body["audit_events"], list)
    assert "exported_at" in body


async def test_export_includes_itineraries(client):
    from app.database import get_session_factory
    from datetime import datetime, timezone, timedelta
    from uuid import uuid4

    email = "export-itin@example.com"
    token = await _register_and_login(client, email, "supersecret1")

    # Resolve the user id via /api/profile/me (pilot card endpoint).
    r = await client.get(
        "/api/profile/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    user_id = r.json()["id"]

    # Seed one saved itinerary for this user.
    factory = get_session_factory()
    async with factory() as session:
        now = datetime.now(timezone.utc)
        itin = SavedItinerary(
            user_id=user_id,
            title="Test trip",
            starts_at=now + timedelta(days=7),
            ends_at=now + timedelta(days=12),
            payload={"events": [], "flights": []},
            total_price_cents=12345,
            currency="USD",
        )
        session.add(itin)
        await session.commit()

    r = await client.get(
        "/api/profile/me/export",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["itineraries"]) == 1
    assert body["itineraries"][0]["title"] == "Test trip"
    assert body["itineraries"][0]["total_price_cents"] == 12345


async def test_export_writes_audit(client):
    email = "export-audit@example.com"
    token = await _register_and_login(client, email, "supersecret1")

    r = await client.get(
        "/api/profile/me/export",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    user_id = body["profile"]["id"]

    # Confirm the audit row landed.
    from app.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(AuditLog).where(
            AuditLog.actor_user_id == user_id,
            AuditLog.action == "gdpr_export",
        )
        rows = (await session.execute(stmt)).scalars().all()
        assert len(rows) == 1
        assert rows[0].action == "gdpr_export"
