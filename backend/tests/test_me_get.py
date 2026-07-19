"""Tests for GET /api/profile/me (single-endpoint pilot).

The endpoint returns the current user's id, email, name, tier,
next_billing_date, home_airport, onboarding_complete, and role.

NOTE: spec says /api/me; current router prefix is /profile, so the
effective URL is /api/profile/me. A follow-up card can split this
router to expose /api/me directly.
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

# Use a per-test SQLite file so each test gets a clean schema. The
# conftest's persistent `./test_travel_scout.db` would otherwise leak
# state across tests in this file (no engine fixture is requested here).
TEST_DB_FILE = f"./test_me_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_FILE}"
os.environ["DATABASE_URL_SYNC"] = f"sqlite:///{TEST_DB_FILE}"

from app.config import get_settings  # noqa: E402
from app.database import Base, dispose_engine, get_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402
import app.models  # noqa: E402,F401  -- registers models on Base.metadata
from app.models import User  # noqa: E402


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    get_settings.cache_clear()
    # Reset the app's engine so it picks up the per-test DATABASE_URL.
    await dispose_engine()
    # Create the schema BEFORE the app's lifespan runs (lifespan seeds
    # reference data, which requires tables to exist).
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
    # Clean up the per-test DB file.
    try:
        os.remove(TEST_DB_FILE)
    except FileNotFoundError:
        pass


async def _register_and_login(client: AsyncClient, email: str, password: str) -> str:
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": "Test User"},
    )
    assert r.status_code in (200, 201), r.text
    r = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_me_requires_auth(client):
    r = await client.get("/api/profile/me")
    assert r.status_code == 401


async def test_me_returns_user(client):
    token = await _register_and_login(client, "pilot-user@example.com", "supersecret1")
    r = await client.get(
        "/api/profile/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # All documented fields present
    for field in (
        "id",
        "email",
        "name",
        "tier",
        "next_billing_date",
        "home_airport",
        "onboarding_complete",
        "role",
    ):
        assert field in body, f"missing field: {field}"
    assert body["email"] == "pilot-user@example.com"
    assert body["tier"] == "free"
    assert body["next_billing_date"] is None
    assert body["home_airport"] is None
    assert body["onboarding_complete"] is False
    assert body["role"] == "user"
    assert isinstance(body["id"], str)


async def test_me_includes_tier(client):
    token = await _register_and_login(client, "tier-user@example.com", "supersecret1")
    # Free tier is the default; confirm via /me.
    r = await client.get(
        "/api/profile/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "free"
    assert body["next_billing_date"] is None


async def test_me_soft_deleted_user(client):
    email = "deleted-user@example.com"
    token = await _register_and_login(client, email, "supersecret1")
    # Soft-delete: flip is_active to False.
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            update(User).where(User.email == email).values(is_active=False)
        )
        await session.commit()
    r = await client.get(
        "/api/profile/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401
