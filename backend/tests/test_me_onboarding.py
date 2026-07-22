"""Tests for POST /api/me/onboarding.

The endpoint stores the 3-step intake wizard result (home airport,
interest keys, destination wishlist) on the current user, flips
``onboarding_complete=True`` (unless ``skippable=True``), and writes
an audit log row. The values round-trip via GET /me, because the
User model now carries the four columns added by migration
``0002_user_onboarding_fields``:

- ``home_airport``           String(8)  nullable
- ``onboarding_complete``    Boolean    NOT NULL default False
- ``interests_json``         JSON       nullable
- ``destinations_json``      JSON       nullable
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# Per-test SQLite file so each test gets a clean schema.
TEST_DB_FILE = f"./test_me_onboarding_{uuid.uuid4().hex}.db"
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
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": "Onboard User"},
    )
    assert r.status_code in (200, 201), r.text
    r = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_onboarding_stores_fields(client):
    """POST /me/onboarding must persist the wizard output and round-trip
    via GET /me.

    Exercises the full persistence path: home_airport, interests_json,
    destinations_json, and the onboarding_complete flag flip.
    """
    email = "onboard-stores@example.com"
    token = await _register_and_login(client, email)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "home_airport": "JNB",
        "interests": ["f1", "jazz"],
        "destinations": ["spa", "monza"],
        "skippable": False,
    }

    r = await client.post("/api/profile/me/onboarding", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"]
    assert body["email"] == email
    assert body["home_airport"] == "JNB"
    assert body["onboarding_complete"] is True
    assert body["interests"] == ["f1", "jazz"]
    assert body["destinations"] == ["spa", "monza"]

    # GET /me round-trips the persisted values.
    r2 = await client.get("/api/profile/me", headers=headers)
    assert r2.status_code == 200, r2.text
    me = r2.json()
    assert me["home_airport"] == "JNB"
    assert me["onboarding_complete"] is True
    assert me["interests"] == ["f1", "jazz"]
    assert me["destinations"] == ["spa", "monza"]

    # Audit row exists with the right action and metadata.
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one()

        audit_result = await session.execute(
            select(AuditLog).where(
                AuditLog.actor_user_id == user.id,
                AuditLog.action == "onboarding_completed",
            )
        )
        row = audit_result.scalar_one_or_none()

    assert row is not None, "no audit log row for onboarding_completed"
    assert row.metadata_json["home_airport"] == "JNB"
    assert row.metadata_json["interests"] == ["f1", "jazz"]
    assert row.metadata_json["destinations"] == ["spa", "monza"]
    assert row.metadata_json["skippable"] is False


async def test_onboarding_is_idempotent(client):
    """Calling the endpoint twice with the same body is fine.

    Each call writes its own audit row (so the operator can see the
    user re-saved their preferences) but the response and final state
    are equivalent.
    """
    email = "onboard-idempotent@example.com"
    token = await _register_and_login(client, email)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "home_airport": "LHR",
        "interests": ["classical"],
        "destinations": ["vienna"],
        "skippable": False,
    }

    r1 = await client.post("/api/profile/me/onboarding", headers=headers, json=payload)
    assert r1.status_code == 200, r1.text
    r2 = await client.post("/api/profile/me/onboarding", headers=headers, json=payload)
    assert r2.status_code == 200, r2.text

    # Both responses agree on the user id and the persisted values.
    assert r1.json()["id"] == r2.json()["id"]
    assert r1.json()["home_airport"] == "LHR"
    assert r2.json()["home_airport"] == "LHR"
    assert r1.json()["onboarding_complete"] is True
    assert r2.json()["onboarding_complete"] is True

    # GET /me still returns the same values (idempotent re-save).
    r3 = await client.get("/api/profile/me", headers=headers)
    assert r3.status_code == 200, r3.text
    assert r3.json()["home_airport"] == "LHR"
    assert r3.json()["interests"] == ["classical"]
    assert r3.json()["destinations"] == ["vienna"]

    # Two audit rows for this user.
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        audit_count = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.actor_user_id == user.id,
                    AuditLog.action == "onboarding_completed",
                )
            )
        ).all()
    assert len(audit_count) == 2


async def test_onboarding_skippable(client):
    """skippable=True must leave onboarding_complete=False on the User
    row and write an onboarding_skipped audit row.

    The UI is expected to re-prompt on next login.
    """
    email = "onboard-skip@example.com"
    token = await _register_and_login(client, email)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "home_airport": "GRU",
        "interests": [],
        "destinations": [],
        "skippable": True,
    }

    r = await client.post("/api/profile/me/onboarding", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["home_airport"] == "GRU"
    assert body["onboarding_complete"] is False
    assert body["interests"] == []
    assert body["destinations"] == []

    # GET /me also reports onboarding_complete=False.
    r2 = await client.get("/api/profile/me", headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["onboarding_complete"] is False

    # Audit row tagged onboarding_skipped.
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        skip_row = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.actor_user_id == user.id,
                    AuditLog.action == "onboarding_skipped",
                )
            )
        ).scalar_one_or_none()
    assert skip_row is not None, "no audit log row for onboarding_skipped"
    assert skip_row.metadata_json["skippable"] is True


async def test_onboarding_requires_auth(client):
    """No JWT → 401."""
    r = await client.post(
        "/api/profile/me/onboarding",
        json={
            "home_airport": "JNB",
            "interests": [],
            "destinations": [],
            "skippable": False,
        },
    )
    assert r.status_code == 401, r.text


async def test_onboarding_rejects_bad_body(client):
    """422 on missing home_airport (Pydantic min_length=3)."""
    email = "onboard-bad@example.com"
    token = await _register_and_login(client, email)
    headers = {"Authorization": f"Bearer {token}"}

    # home_airport too short.
    r = await client.post(
        "/api/profile/me/onboarding",
        headers=headers,
        json={"home_airport": "J", "interests": [], "destinations": []},
    )
    assert r.status_code == 422, r.text

    # home_airport missing entirely.
    r2 = await client.post(
        "/api/profile/me/onboarding",
        headers=headers,
        json={"interests": [], "destinations": []},
    )
    assert r2.status_code == 422, r2.text
