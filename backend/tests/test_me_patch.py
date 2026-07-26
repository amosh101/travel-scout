"""Tests for PATCH /api/profile/me.

The endpoint updates the current user's profile (name, nationality,
passport, dob, emergency contact, etc.), writes an audit log row, and
rejects attempts to change email/tier through this route.
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# Per-test SQLite file so each test gets a clean schema (the conftest's
# persistent DB would otherwise leak state across tests in this file).
TEST_DB_FILE = f"./test_me_patch_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_FILE}"
os.environ["DATABASE_URL_SYNC"] = f"sqlite:///{TEST_DB_FILE}"

from app.config import get_settings  # noqa: E402
from app.database import Base, dispose_engine, get_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402
import app.models  # noqa: E402,F401  -- registers models on Base.metadata
from app.models import AuditLog, User  # noqa: E402


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    get_settings.cache_clear()
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
    try:
        os.remove(TEST_DB_FILE)
    except FileNotFoundError:
        pass


async def _register_and_login(
    client: AsyncClient, email: str, password: str = "supersecret1"
) -> str:
    """Register, log in, return the access token."""
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": "Original Name"},
    )
    assert r.status_code in (200, 201), r.text
    r = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_patch_me_updates_name(client):
    token = await _register_and_login(client, "patch-name@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.patch(
        "/api/profile/me",
        headers=headers,
        json={"name": "Renamed User"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Renamed User"

    # Confirm persistence via next GET.
    r2 = await client.get("/api/profile/me", headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["name"] == "Renamed User"


async def test_patch_me_rejects_email_change(client):
    """Email and tier are not updatable through PATCH /me.

    The PATCH schema has no `email` field, so sending one is rejected
    with 422 by Pydantic.
    """
    token = await _register_and_login(client, "patch-email@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.patch(
        "/api/profile/me",
        headers=headers,
        json={"email": "hijacked@example.com"},
    )
    assert r.status_code == 422, r.text


async def test_patch_me_requires_auth(client):
    r = await client.patch(
        "/api/profile/me",
        json={"name": "Should Not Apply"},
    )
    assert r.status_code == 401


async def test_patch_me_writes_audit_log(client):
    """A successful PATCH must write an audit row with action='profile_update'."""
    email = "patch-audit@example.com"
    token = await _register_and_login(client, email)
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.patch(
        "/api/profile/me",
        headers=headers,
        json={"name": "Audited User", "nationality": "MZ"},
    )
    assert r.status_code == 200, r.text

    factory = get_session_factory()
    async with factory() as session:
        # Find the user we just registered.
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one()

        # Find the audit row this PATCH should have written.
        audit_result = await session.execute(
            select(AuditLog).where(
                AuditLog.actor_user_id == user.id,
                AuditLog.action == "profile_update",
            )
        )
        row = audit_result.scalar_one_or_none()

    assert row is not None, "no audit log row found for profile_update"
    fields = row.metadata_json.get("fields", [])
    assert "name" in fields
    assert "nationality" in fields
