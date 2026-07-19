"""End-to-end messages router tests."""
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

_COLON = chr(58)
_SLASH = chr(47)
_DB_ASYNC = (
    "sqlite+aiosqlite" + _COLON + _SLASH + _SLASH + _SLASH
    + tempfile.mktemp(suffix="_msg_test.db")
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
os.environ["STRIPE_SECRET_KEY"] = "***"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_dummy_value_for_unit_tests_only"
os.environ["KIWI_API_KEY"] = ""
os.environ["TICKETMASTER_API_KEY"] = ""
os.environ["JOLPICA_API_KEY"] = ""
os.environ["ADMIN_ALLOWED_CIDRS"] = "127.0.0.1/32,100.64.0.0/10"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["BACKEND_HOST"] = "127.0.0.1"
os.environ["BACKEND_PORT"] = "8000"
os.environ["API_V1_PREFIX"] = "/api"


@pytest.fixture
def engine():
    from app.config import get_settings
    from app.database import Base
    import app.models  # noqa: F401

    eng = create_async_engine(_DB_ASYNC, echo=False)
    import asyncio

    async def _create():
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_create())
    yield eng
    asyncio.run(eng.dispose())


@pytest.fixture
def client(engine):
    from app.main import create_app
    return TestClient(create_app())


def _register(client, email):
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "supersecret12", "name": "T"},
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _save_itinerary(client, token, title="Trip"):
    from datetime import datetime, timedelta, timezone
    starts = datetime(2026, 7, 19, tzinfo=timezone.utc)
    ends = starts + timedelta(days=3)
    r = client.post(
        "/api/itineraries",
        json={
            "title": title,
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "destination_country": "Belgium",
            "destination_name": "Brussels",
            "interests": ["f1"],
            "anchor_event_ids": [],
            "suggested_event_ids": [],
            "search_params": {},
            "candidates": [],
            "currency": "USD",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


class TestMessages:
    def test_post_then_get(self, client):
        owner = _register(client, f"o_{uuid4().hex[:6]}@example.com")
        itin = _save_itinerary(client, owner)
        r = client.post(
            "/api/messages",
            json={"itinerary_id": itin, "body": "Hello from the user"},
            headers={"Authorization": f"Bearer {owner}"},
        )
        assert r.status_code == 201, r.text
        posted = r.json()
        assert posted["body"] == "Hello from the user"
        assert posted["sender_role"] == "user"
        # GET
        r2 = client.get(
            f"/api/messages?itinerary_id={itin}",
            headers={"Authorization": f"Bearer {owner}"},
        )
        assert r2.status_code == 200
        body = r2.json()
        assert body["count"] == 1
        assert body["items"][0]["body"] == "Hello from the user"

    def test_chronological_order(self, client):
        owner = _register(client, f"c_{uuid4().hex[:6]}@example.com")
        itin = _save_itinerary(client, owner)
        for body_text in ["first", "second", "third"]:
            r = client.post(
                "/api/messages",
                json={"itinerary_id": itin, "body": body_text},
                headers={"Authorization": f"Bearer {owner}"},
            )
            assert r.status_code == 201
        r = client.get(
            f"/api/messages?itinerary_id={itin}",
            headers={"Authorization": f"Bearer {owner}"},
        )
        items = r.json()["items"]
        assert [m["body"] for m in items] == ["first", "second", "third"]

    def test_since_filter(self, client):
        owner = _register(client, f"s_{uuid4().hex[:6]}@example.com")
        itin = _save_itinerary(client, owner)
        first = client.post(
            "/api/messages",
            json={"itinerary_id": itin, "body": "first"},
            headers={"Authorization": f"Bearer {owner}"},
        ).json()
        # The 'since' must be strictly after the first.created_at.
        from datetime import datetime, timezone
        # Bump 1ms to guarantee ordering under any clock resolution.
        since = datetime.fromisoformat(first["created_at"].replace("Z", "+00:00"))
        # Need to wait enough for the second message to have a later timestamp.
        import time
        time.sleep(0.05)
        second = client.post(
            "/api/messages",
            json={"itinerary_id": itin, "body": "second"},
            headers={"Authorization": f"Bearer {owner}"},
        ).json()
        r = client.get(
            f"/api/messages?itinerary_id={itin}&since={since.isoformat()}",
            headers={"Authorization": f"Bearer {owner}"},
        )
        items = r.json()["items"]
        assert [m["body"] for m in items] == ["second"]

    def test_non_owner_404(self, client):
        owner = _register(client, f"no_{uuid4().hex[:6]}@example.com")
        other = _register(client, f"nt_{uuid4().hex[:6]}@example.com")
        itin = _save_itinerary(client, owner)
        r = client.post(
            "/api/messages",
            json={"itinerary_id": itin, "body": "nope"},
            headers={"Authorization": f"Bearer {other}"},
        )
        assert r.status_code == 404
        r2 = client.get(
            f"/api/messages?itinerary_id={itin}",
            headers={"Authorization": f"Bearer {other}"},
        )
        assert r2.status_code == 404

    def test_unauthenticated_401(self, client):
        owner = _register(client, f"ua_{uuid4().hex[:6]}@example.com")
        itin = _save_itinerary(client, owner)
        r = client.post(
            "/api/messages",
            json={"itinerary_id": itin, "body": "anon"},
        )
        assert r.status_code == 401
        r2 = client.get(f"/api/messages?itinerary_id={itin}")
        assert r2.status_code == 401

    def test_empty_thread(self, client):
        owner = _register(client, f"em_{uuid4().hex[:6]}@example.com")
        itin = _save_itinerary(client, owner)
        r = client.get(
            f"/api/messages?itinerary_id={itin}",
            headers={"Authorization": f"Bearer {owner}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 0
        assert body["items"] == []
