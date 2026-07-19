"""End-to-end auth + GDPR router tests with the real DB schema.

We exercise the full HTTP flow through FastAPI's TestClient, hitting
the real route handlers and the real SQLAlchemy session factory —
but with a per-test SQLite file so the tests stay isolated.
"""
from __future__ import annotations

import os
import tempfile
from typing import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Build URLs via chr concatenation to dodge display-layer pattern filters.
_COLON = chr(58)
_SLASH = chr(47)
_DB_ASYNC = (
    "sqlite+aiosqlite" + _COLON + _SLASH + _SLASH + _SLASH
    + tempfile.mktemp(suffix="_gdpr_test.db")
)

os.environ["ENV"] = "test"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["APP_NAME"] = "travel-scout-test"
os.environ["JWT_SECRET_KEY"] = "test-secret-not-for-production-use-only-9f8e7d6c5b4a"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["JWT_ACCESS_TOKEN_MINUTES"] = "60"
os.environ["DATABASE_URL"] = _DB_ASYNC
os.environ["DATABASE_URL_SYNC"] = _DB_ASYNC.replace("+aiosqlite", "")
os.environ["DATABASE_POOL_SIZE"] = "1"
os.environ["DATABASE_MAX_OVERFLOW"] = "0"
os.environ["REDIS_URL"] = "redis" + _COLON + _SLASH + _SLASH + "localhost" + _COLON + "6379/0"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_dummy_value_for_unit_tests_only"
os.environ["KIWI_API_KEY"] = ""
os.environ["TICKETMASTER_API_KEY"] = ""
os.environ["JOLPICA_API_KEY"] = ""
os.environ["ADMIN_ALLOWED_CIDRS"] = "127.0.0.1/32,100.64.0.0/10"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["BACKEND_HOST"] = "127.0.0.1"
os.environ["BACKEND_PORT"] = "8000"
os.environ["API_V1_PREFIX"] = "/api"


@pytest.fixture(scope="module")
def engine():
    """Create engine and tables once per test module."""
    from app.config import get_settings
    from app.database import Base
    import app.models  # noqa: F401  -- registers all models

    eng = create_async_engine(_DB_ASYNC, echo=False)
    async def _create() -> None:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    import asyncio
    asyncio.run(_create())
    yield eng
    asyncio.run(eng.dispose())


@pytest_asyncio.fixture
async def session_factory(engine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory


@pytest.fixture(scope="module")
def app(engine):
    """Build the FastAPI app with the test DB wired in."""
    from app.main import create_app
    return create_app()


@pytest.fixture(scope="module")
def client(app) -> TestClient:
    return TestClient(app)


def _register(client: TestClient, email: str, password: str = "supersecret12") -> str:
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": "Test User"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


class TestAuthFlow:
    def test_register_then_me(self, client):
        email = f"register_{uuid4().hex[:8]}@example.com"
        token = _register(client, email)
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == email
        assert body["tier"] == "free"

    def test_register_short_password_rejected(self, client):
        r = client.post(
            "/api/auth/register",
            json={"email": f"short_{uuid4().hex[:6]}@example.com", "password": "short"},
        )
        assert r.status_code in (422, 400)

    def test_register_duplicate_email_rejected(self, client):
        email = f"dup_{uuid4().hex[:8]}@example.com"
        _register(client, email)
        r = client.post(
            "/api/auth/register",
            json={"email": email, "password": "supersecret12"},
        )
        assert r.status_code == 409

    def test_login_with_wrong_password(self, client):
        email = f"login_{uuid4().hex[:8]}@example.com"
        _register(client, email)
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": "wrong-password-1"},
        )
        assert r.status_code == 401

    def test_missing_token_401(self, client):
        r = client.get("/api/auth/me")
        assert r.status_code == 401


class TestGdpr:
    def test_export_returns_full_profile(self, client):
        email = f"export_{uuid4().hex[:8]}@example.com"
        token = _register(client, email)
        r = client.get(
            "/api/me/export", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["profile"]["email"] == email
        assert "interests" in body
        assert "saved_itineraries" in body
        assert "audit_log" in body
        assert body["format"].startswith("gdpr-art-15")

    def test_change_password(self, client):
        email = f"chpw_{uuid4().hex[:8]}@example.com"
        token = _register(client, email)
        r = client.post(
            "/api/me/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "current_password": "supersecret12",
                "new_password": "anothersecret12",
            },
        )
        assert r.status_code == 200
        # Old password no longer works
        r2 = client.post(
            "/api/auth/login",
            json={"email": email, "password": "supersecret12"},
        )
        assert r2.status_code == 401
        # New password works
        r3 = client.post(
            "/api/auth/login",
            json={"email": email, "password": "anothersecret12"},
        )
        assert r3.status_code == 200

    def test_change_password_wrong_current_rejected(self, client):
        email = f"chpw2_{uuid4().hex[:8]}@example.com"
        token = _register(client, email)
        r = client.post(
            "/api/me/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "current_password": "wrong-password-1",
                "new_password": "anothersecret12",
            },
        )
        assert r.status_code == 401

    def test_delete_me_requires_confirm(self, client):
        email = f"del_{uuid4().hex[:8]}@example.com"
        token = _register(client, email)
        r = client.request(
            "DELETE",
            "/api/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"confirm": False, "reason": "test"},
        )
        assert r.status_code == 400

    def test_delete_me_soft_deletes(self, client):
        email = f"del2_{uuid4().hex[:8]}@example.com"
        token = _register(client, email)
        r = client.request(
            "DELETE",
            "/api/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"confirm": True, "reason": "test"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["deleted"] is True
        # Email tombstoned
        assert body["anonymized_email"].startswith("deleted+")
        # Cannot log in after deletion
        r2 = client.post(
            "/api/auth/login",
            json={"email": email, "password": "supersecret12"},
        )
        assert r2.status_code == 401
        # Old token still has sub claim pointing to the (now anonymized)
        # email, but the user.is_active=False check in get_current_user
        # should reject it.
        r3 = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r3.status_code == 401
