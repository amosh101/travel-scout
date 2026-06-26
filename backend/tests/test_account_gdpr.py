"""
TDD tests for the GDPR account router (app/routers/account.py).

TDD discipline: these tests are written BEFORE the implementation.
The router (app.routers.account) must expose:
  POST /api/account/delete    — GDPR right to erasure (soft-delete + audit row)
  POST /api/account/export    — GDPR data portability (full JSON dump + audit row)
  GET  /api/account/audit     — current user's audit log, most-recent first

These tests use:
  - a local in-memory SQLite session (mirrors the conftest pattern)
  - a minimal FastAPI app with ONLY the account router mounted
  - app.dependency_overrides to swap get_db (real db) and get_current_user (fake)

This isolation prevents the test from depending on the production app wiring
in app/main.py or the global engine in app/database.py.

We test three behaviors per endpoint:
  1. Auth gate (no token → 401)
  2. Happy path (with auth → correct side effects)
  3. Audit trail (where applicable)

Plus shape/order/cap invariants on /audit.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import AuditLog, Interest, User
from app.services.user_repo import UserRepository


# All tests in this module are async (httpx TestClient is sync but the
# surrounding fixtures and assertions are best expressed async).
pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Local fixtures (mirrors the conftest.py pattern; pytest-asyncio strict mode
# requires @pytest_asyncio.fixture for async fixtures).
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session():
    """Clean in-memory SQLite session per test."""
    from app.models import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_user(db_session):
    """Create one user row in the DB and return it.

    The returned object's .id matches the row in the DB (UserRepository
    flushes before returning, so refresh() sees the assigned UUID).
    """
    repo = UserRepository(db_session)
    user = await repo.create_user(
        email="alice@example.com",
        password="supersecret123",
        display_name="Alice",
    )
    await db_session.commit()
    # Detach so the route can use the same object after commit (refresh if needed)
    return user


@pytest_asyncio.fixture
async def app_client(db_session, seeded_user):
    """Build a minimal FastAPI app with the account router mounted and
    dependency_overrides installed for get_db and get_current_user.

    Returns (client, session, user).
    """
    # Lazy import so an unimplemented router fails the test loudly (we
    # want import-time errors to show up as test failures, not skips).
    from app.routers.account import router as account_router
    from app.routers.auth import get_current_user
    from app.database import get_db

    app = FastAPI()
    app.include_router(account_router)

    # get_db → real test session
    async def _override_get_db():
        try:
            yield db_session
        finally:
            # Don't close: the fixture owns the session lifecycle.
            pass

    # get_current_user → the seeded user
    async def _override_get_current_user():
        return seeded_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    # Attach a fake request.client so the audit rows get an ip_address.
    # TestClient doesn't expose a request.client.host by default, so we
    # add a tiny middleware that always sets it.
    @app.middleware("http")
    async def _attach_client(request: Request, call_next):
        # Starlette's TestClient provides request.client when the request
        # comes through the ASGI transport, so we don't need to fake it.
        return await call_next(request)

    client = TestClient(app)
    yield client, db_session, seeded_user

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def unauthed_client(db_session):
    """Build a minimal FastAPI app WITHOUT auth override — used to test 401."""
    from app.routers.account import router as account_router
    from app.database import get_db

    app = FastAPI()
    app.include_router(account_router)

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    # NOTE: get_current_user is NOT overridden → real OAuth2 flow runs →
    # 401 (missing/invalid token) is what we expect.

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


# ===========================================================================
# /api/account/delete
# ===========================================================================


async def test_delete_requires_auth(unauthed_client):
    """POST /api/account/delete with no auth header → 401."""
    client = unauthed_client

    response = client.post("/api/account/delete")

    assert response.status_code == 401, (
        f"Unauthenticated delete must be rejected; got {response.status_code}: {response.text}"
    )


async def test_delete_soft_deletes_user(app_client):
    """POST /api/account/delete with auth → user's is_active becomes False."""
    client, db_session, user = app_client

    # Sanity: user starts active
    assert user.is_active is True

    response = client.post("/api/account/delete")

    assert response.status_code == 200, (
        f"Authenticated delete should succeed; got {response.status_code}: {response.text}"
    )

    # Reload the user from the DB and check side effects
    fresh = await UserRepository(db_session).get_by_id(user.id)
    assert fresh is not None, "User row should still exist (soft-delete, not hard)"
    assert fresh.is_active is False, "soft_delete must set is_active=False"
    assert fresh.email.startswith("deleted-"), (
        f"PII must be cleared; email should be 'deleted-<uuid>', got {fresh.email!r}"
    )
    assert fresh.name is None, "PII (name) must be cleared"


async def test_delete_writes_audit_log(app_client):
    """POST /api/account/delete writes exactly one audit_log row with action='account.delete'."""
    from sqlalchemy import func, select

    client, db_session, user = app_client

    response = client.post("/api/account/delete")

    assert response.status_code == 200

    # Count rows
    count = (
        await db_session.execute(select(func.count(AuditLog.id)))
    ).scalar_one()
    assert count == 1, f"Expected 1 audit_log row, got {count}"

    # Inspect the row
    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert rows[0].action == "account.delete"
    assert rows[0].user_id == user.id
    assert rows[0].target_type == "user"
    assert rows[0].target_id == str(user.id)


async def test_delete_response_shape(app_client):
    """POST /api/account/delete returns {message, deleted_utc} with deleted_utc as ISO 8601."""
    client, _db, _user = app_client

    response = client.post("/api/account/delete")

    assert response.status_code == 200
    body = response.json()
    assert "message" in body, f"Response must include 'message' key; got {body!r}"
    assert "deleted_utc" in body, f"Response must include 'deleted_utc' key; got {body!r}"
    assert body["message"] == "Account deleted"

    # ISO 8601 — accept the format we use elsewhere in the codebase.
    # datetime.fromisoformat handles '...T...+00:00' and '...T...Z' in 3.11+.
    parsed = datetime.fromisoformat(body["deleted_utc"].replace("Z", "+00:00"))
    assert isinstance(parsed, datetime)


# ===========================================================================
# /api/account/export
# ===========================================================================


async def test_export_requires_auth(unauthed_client):
    """POST /api/account/export with no auth header → 401."""
    client = unauthed_client

    response = client.post("/api/account/export")

    assert response.status_code == 401, (
        f"Unauthenticated export must be rejected; got {response.status_code}: {response.text}"
    )


async def test_export_returns_user_dict(app_client):
    """POST /api/account/export with auth → response has 'user' key with email."""
    client, _db, user = app_client

    response = client.post("/api/account/export")

    assert response.status_code == 200, (
        f"Authenticated export should succeed; got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert "user" in body, f"Response must include 'user' key; got {body!r}"
    assert body["user"]["email"] == user.email, (
        f"Exported user.email should match; got {body['user']['email']!r}"
    )


async def test_export_includes_interests_when_present(app_client):
    """Create an Interest for the user → export response contains an 'interests' array with it."""
    client, db_session, user = app_client

    interest = Interest(
        user_id=user.id,
        name="F1 races in Europe",
        origin_airport="JFK",
        destination_region="EU",
        event_keywords="formula 1",
    )
    db_session.add(interest)
    await db_session.commit()

    response = client.post("/api/account/export")

    assert response.status_code == 200
    body = response.json()
    assert "interests" in body, f"Response must include 'interests' key; got {body!r}"
    assert isinstance(body["interests"], list)
    assert len(body["interests"]) >= 1, "Exported interests should include the one we created"
    names = {i.get("name") for i in body["interests"]}
    assert "F1 races in Europe" in names


async def test_export_writes_audit_log(app_client):
    """POST /api/account/export writes exactly one audit_log row with action='account.export'."""
    from sqlalchemy import func, select

    client, db_session, user = app_client

    response = client.post("/api/account/export")

    assert response.status_code == 200

    count = (
        await db_session.execute(select(func.count(AuditLog.id)))
    ).scalar_one()
    assert count == 1, f"Expected 1 audit_log row, got {count}"

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert rows[0].action == "account.export"
    assert rows[0].user_id == user.id


# ===========================================================================
# /api/account/audit
# ===========================================================================


async def test_audit_requires_auth(unauthed_client):
    """GET /api/account/audit with no auth header → 401."""
    client = unauthed_client

    response = client.get("/api/account/audit")

    assert response.status_code == 401, (
        f"Unauthenticated audit list must be rejected; got {response.status_code}: {response.text}"
    )


async def test_audit_returns_user_rows_only(app_client):
    """Audit query is scoped to current_user — other users' rows are invisible."""
    from sqlalchemy import select

    client, db_session, user = app_client

    # Build a second user with their own audit row
    other_repo = UserRepository(db_session)
    other_user = await other_repo.create_user(
        email="bob@example.com",
        password="bobspassword",
        display_name="Bob",
    )
    await db_session.commit()

    # Seed 2 rows for our user, 1 for the other user
    db_session.add(AuditLog(action="user.login", user_id=user.id))
    db_session.add(AuditLog(action="user.view",  user_id=user.id))
    db_session.add(AuditLog(action="user.login", user_id=other_user.id))
    await db_session.commit()

    response = client.get("/api/account/audit")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 2, (
        f"Should only see current_user's rows; got {len(body)}: {body!r}"
    )
    # All rows must belong to current_user (user_id is not in the response
    # shape per spec, but the count + the actions should be our 2 rows)
    actions = {row["action"] for row in body}
    assert "user.login" in actions or "user.view" in actions


async def test_audit_respects_limit(app_client):
    """?limit=2 caps the response at 2 rows even when more exist."""
    from sqlalchemy import select

    client, db_session, _user = app_client

    for i in range(5):
        db_session.add(AuditLog(action=f"event.{i}", user_id=_user.id))
    await db_session.commit()

    response = client.get("/api/account/audit?limit=2")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2, f"Expected 2 rows with limit=2, got {len(body)}"


async def test_audit_caps_limit_at_200(app_client):
    """?limit=10000 must be capped at 200 — the endpoint enforces a hard ceiling."""
    from sqlalchemy import select

    client, db_session, _user = app_client

    # Write 201 rows (one over the cap) — limit=10000 must still cap at 200.
    for i in range(201):
        db_session.add(AuditLog(action=f"event.{i}", user_id=_user.id))
    await db_session.commit()

    response = client.get("/api/account/audit?limit=10000")

    assert response.status_code == 200
    body = response.json()
    assert len(body) <= 200, (
        f"Limit cap must be 200; got {len(body)} rows when limit=10000"
    )
    # Be exact: with 201 rows and a 200 cap, we should get exactly 200.
    assert len(body) == 200


async def test_audit_ordered_most_recent_first(app_client):
    """Newer occurred_utc comes first (DESC ordering)."""
    from sqlalchemy import select

    client, db_session, _user = app_client

    t_old = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    t_new = datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc)

    db_session.add(AuditLog(action="event.first",  user_id=_user.id, occurred_utc=t_old))
    db_session.add(AuditLog(action="event.second", user_id=_user.id, occurred_utc=t_new))
    await db_session.commit()

    response = client.get("/api/account/audit")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["action"] == "event.second", (
        f"Most recent row should come first; got {body[0]['action']!r}"
    )
    assert body[1]["action"] == "event.first"
    # Also sanity-check the timestamps
    assert body[0]["occurred_utc"] > body[1]["occurred_utc"], (
        "occurred_utc should be strictly decreasing across the list"
    )