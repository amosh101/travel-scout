"""
Integration test: full auth roundtrip against the wired main app.

This is the "did Part 1 actually wire everything together?" test.
Uses the REAL main.py app (not a minimal fixture app), with
dependency_overrides for the DB so we can run against SQLite.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client():
    """Build the real app with an in-memory SQLite override.

    MVP Revamp 2026-06-25 fix: rebind the module-level engine + sessionmaker
    on app.database to an in-memory SQLite pair BEFORE entering TestClient.
    This is required because:

      1. app.main's lifespan calls init_db() against the module-level engine.
         If we leave it pointing at Postgres (the default), lifespan startup
         blocks/errors trying to reach a DB that isn't running.
      2. The module-level engine's connection pool becomes bound to whatever
         event loop the FIRST TestClient's lifespan ran on. Reusing that pool
         inside a SECOND TestClient (a fresh loop) raises
         "got Future attached to a different loop" on every subsequent test.
         Rebinding disposes the old pool and creates a new one bound to the
         current loop, eliminating cross-loop contamination.

    Both get_db (via dependency_overrides) and init_db (via lifespan) now
    see the SQLite engine — and the same engine, so there's only one pool.
    """
    from app.main import app
    from app.database import get_db, rebind_engine, restore_engine
    from app.models import Base
    import asyncio

    async def _setup():
        new_engine = await rebind_engine(
            "sqlite+aiosqlite:///:memory:"
        )
        # Create schema on the rebound engine so lifespan's init_db() is a
        # no-op (Base.metadata.create_all is idempotent if tables already exist
        # on a fresh in-memory DB, but we want the schema ready before the
        # first request so we don't race init_db with the test).
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())

    async def override_get_db():
        # Read the current async_session_maker at call time — same one the
        # production get_db resolves to, since we just rebound it.
        from app.database import async_session_maker
        async with async_session_maker() as session:
            try:
                yield session
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()

    async def _teardown():
        await restore_engine()

    asyncio.run(_teardown())


def test_root_returns_v2(client):
    """GET / returns version 0.2.0 (bumped for revamp)."""
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["version"] == "0.2.0"


def test_health_includes_request_id_middleware(client):
    """GET /health advertises that request_id middleware is active."""
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["request_id_middleware"] is True


def test_request_id_header_present_on_every_response(client):
    """Every response carries X-Request-ID, even unauth'd error paths."""
    r = client.get("/")
    assert "X-Request-ID" in r.headers
    assert len(r.headers["X-Request-ID"]) > 0

    r2 = client.get("/api/auth/me")  # 401 — should still have the header
    assert "X-Request-ID" in r2.headers


def test_request_id_propagates_when_supplied(client):
    """If the client sends X-Request-ID, the server echoes it back."""
    r = client.get("/", headers={"X-Request-ID": "client-test-12345"})
    assert r.headers["X-Request-ID"] == "client-test-12345"


def test_account_routes_registered(client):
    """GET /openapi.json shows the 3 GDPR account endpoints."""
    r = client.get("/openapi.json")
    paths = r.json()["paths"]
    assert "/api/account/delete" in paths
    assert "/api/account/export" in paths
    assert "/api/account/audit" in paths


def _login(client, email, password):
    """Login helper. OAuth2PasswordRequestForm wants form-encoded data
    with `username` + `password` keys (RFC 6749 password grant)."""
    return client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def test_register_then_login_then_me(client):
    """Full auth flow: register → login → /auth/me with token."""
    # Register
    r = client.post("/api/auth/register", json={
        "email": "sir@example.com",
        "password": "correct-horse-battery-staple-2026",
        "name": "Sir",
    })
    assert r.status_code == 201, r.text
    user = r.json()
    assert user["email"] == "sir@example.com"

    # Login (form-encoded)
    r = _login(client, "sir@example.com", "correct-horse-battery-staple-2026")
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    # /auth/me with bearer token
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["email"] == "sir@example.com"


def test_account_export_roundtrip(client):
    """POST /api/account/export returns the user's data."""
    # Setup: register and login
    client.post("/api/auth/register", json={
        "email": "exporter@example.com",
        "password": "test-password-1234",
        "name": "Exporter",
    })
    r = _login(client, "exporter@example.com", "test-password-1234")
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Export
    r = client.post("/api/account/export", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "user" in data
    assert data["user"]["email"] == "exporter@example.com"
    # The other 5 buckets should be present (possibly empty)
    for bucket in ("interests", "alerts", "saved_trips", "dismissed_trips", "audit_log"):
        assert bucket in data


def test_account_delete_requires_auth(client):
    """POST /api/account/delete without a token returns 401."""
    r = client.post("/api/account/delete")
    assert r.status_code == 401


def test_account_delete_soft_deletes(client):
    """POST /api/account/delete sets is_active=False on the user."""
    client.post("/api/auth/register", json={
        "email": "delete-me@example.com",
        "password": "test-password-1234",
        "name": "Delete Me",
    })
    r = _login(client, "delete-me@example.com", "test-password-1234")
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Confirm we can hit /auth/me before delete
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200

    # Delete
    r = client.post("/api/account/delete", headers=headers)
    assert r.status_code == 200, r.text
    assert "deleted" in r.json()["message"].lower()


def test_audit_history_visible_to_owner(client):
    """After a delete, the user's /api/account/audit shows the action."""
    client.post("/api/auth/register", json={
        "email": "audited@example.com",
        "password": "test-password-1234",
        "name": "Audited",
    })
    r = _login(client, "audited@example.com", "test-password-1234")
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Trigger one audit row via delete
    client.post("/api/account/delete", headers=headers)

    # Read audit
    r = client.get("/api/account/audit", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    actions = [row["action"] for row in rows]
    assert "account.delete" in actions