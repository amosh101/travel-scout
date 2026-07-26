"""Tests for DELETE /api/profile/me (GDPR soft delete).

NOTE: spec says /api/me; current router prefix is /profile, so the
effective URL is /api/profile/me — same convention as the sibling
``test_me_get.py`` and ``test_me_export.py`` files.

Soft-delete mechanism: ``user.is_active = False``. The body of the
task spec called for setting ``user.deleted_at = now()`` /
``user.blocked_at = now()``, but those columns do not exist on the
``User`` model and the task hard rules forbid adding new DB columns
or changing the model. ``is_active`` is the existing soft-delete
lever — login and ``get_current_user`` both reject inactive users
with 401 (see auth.py:147 and authz re-export), and the sibling
``test_me_soft_deleted_user`` in test_me_get.py already pins this
convention. A follow-up card can introduce explicit
``deleted_at`` / ``blocked_at`` columns if a distinction between
"disabled by admin" and "deleted by user" is needed.
"""
from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# Per-test SQLite file so each test gets a clean schema.
TEST_DB_FILE = f"./test_me_delete_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_FILE}"
os.environ["DATABASE_URL_SYNC"] = f"sqlite:///{TEST_DB_FILE}"

from app.config import get_settings  # noqa: E402
from app.database import Base, dispose_engine  # noqa: E402
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


async def _register_and_login(client: AsyncClient, email: str, password: str) -> str:
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "name": "Delete User"},
    )
    assert r.status_code in (200, 201), r.text
    r = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_delete_me_soft_deletes(client):
    """DELETE /api/profile/me -> 204; subsequent GET /me with the same
    token must return 401 because the user is now inactive."""
    email = "delete-me@example.com"
    token = await _register_and_login(client, email, "supersecret1")

    r = await client.delete(
        "/api/profile/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 204, r.text

    r = await client.get(
        "/api/profile/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401


async def test_deleted_user_cannot_login(client):
    """After DELETE /me, the same credentials must no longer log in."""
    email = "delete-login@example.com"
    password = "supersecret1"
    token = await _register_and_login(client, email, password)

    r = await client.delete(
        "/api/profile/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 204, r.text

    r = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 401


async def test_delete_writes_audit(client):
    """DELETE /me must persist a single audit row with action='gdpr_delete'."""
    from app.database import get_session_factory

    email = "delete-audit@example.com"
    token = await _register_and_login(client, email, "supersecret1")

    r = await client.delete(
        "/api/profile/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 204, r.text

    # Resolve user id via DB (we just deleted the token-bearing session).
    factory = get_session_factory()
    async with factory() as session:
        user_id = (
            await session.execute(select(User.id).where(User.email == email))
        ).scalar_one()

        rows = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.actor_user_id == user_id,
                    AuditLog.action == "gdpr_delete",
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].action == "gdpr_delete"
        # Soft-deleted user is the target of their own action.
        assert rows[0].target_kind == "user"
        assert rows[0].target_id == str(user_id)


async def test_delete_requires_auth(client):
    """DELETE /me without a JWT must return 401, not 204."""
    r = await client.delete("/api/profile/me")
    assert r.status_code == 401
