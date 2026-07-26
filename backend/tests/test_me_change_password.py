"""Tests for POST /api/profile/me/change-password.

NOTE: spec says /api/me; current router prefix is /profile, so the
effective URL is /api/profile/me/change-password. Same convention as
test_me_get.py.
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

# Per-test SQLite file so each test gets a clean schema (matches
# test_me_onboarding.py's pattern — without this, the tables never
# get created in the test engine and registration fails with
# "no such table: users").
TEST_DB_FILE = f"./test_me_change_password_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_FILE}"
os.environ["DATABASE_URL_SYNC"] = f"sqlite:///{TEST_DB_FILE}"

from app.config import get_settings  # noqa: E402
from app.database import Base, dispose_engine  # noqa: E402
from app.main import create_app  # noqa: E402
import app.models  # noqa: E402,F401  -- registers models on Base.metadata


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
        json={"email": email, "password": password, "name": "Test User"},
    )
    assert r.status_code in (200, 201), r.text
    r = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_change_password_requires_auth(client):
    r = await client.post(
        "/api/profile/me/change-password",
        json={"old_password": "supersecret1", "new_password": "newsecret9"},
    )
    assert r.status_code == 401


async def test_change_password_short_new(client):
    token = await _register_and_login(client, "short-new@example.com", "supersecret1")
    r = await client.post(
        "/api/profile/me/change-password",
        json={"old_password": "supersecret1", "new_password": "short"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422, r.text


async def test_change_password_wrong_old(client):
    token = await _register_and_login(client, "wrong-old@example.com", "supersecret1")
    r = await client.post(
        "/api/profile/me/change-password",
        json={"old_password": "not-the-real-one", "new_password": "newsecret9"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text


async def test_change_password_happy_path(client):
    email = "happy-path@example.com"
    old_pw = "supersecret1"
    new_pw = "brandnewpass2"
    token = await _register_and_login(client, email, old_pw)

    r = await client.post(
        "/api/profile/me/change-password",
        json={"old_password": old_pw, "new_password": new_pw},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 204, r.text

    # Old password should no longer work.
    r = await client.post(
        "/api/auth/login",
        json={"email": email, "password": old_pw},
    )
    assert r.status_code == 401, r.text

    # New password should work.
    r = await client.post(
        "/api/auth/login",
        json={"email": email, "password": new_pw},
    )
    assert r.status_code == 200, r.text
    new_token = r.json()["access_token"]
    assert new_token

    # /me should still respond with the new token.
    r = await client.get(
        "/api/profile/me",
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["email"] == email
