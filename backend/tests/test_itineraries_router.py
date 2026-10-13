"""
Tests for the itineraries router (app/routers/itineraries.py).

The router exposes:
  POST /api/itineraries/find
      Auth required. Reads the user's interests, runs the intersection
      algorithm against the events catalog, composes a day-by-day
      itinerary for each candidate (attaching flights), and returns
      ranked results. Persists nothing by default — the user can save
      individual trips from the result.

  GET /api/itineraries
      Auth required. List the user's saved trips (SavedTrip rows).

  POST /api/itineraries/{trip_id}/save
      Auth required. Persist one of the find results as a SavedTrip
      so the user can retrieve it later (and so future /find runs can
      detect "you saved this last week").

  POST /api/itineraries/{trip_id}/dismiss
      Auth required. Mark an intersection_id as dismissed. Future /find
      runs exclude it.

  GET /api/itineraries/{trip_id}
      Auth required. Retrieve one saved trip.

Pattern (mirrors test_account_gdpr.py):
  - Minimal FastAPI app with ONLY the itineraries router mounted
  - dependency_overrides swap get_db and get_current_user
  - Logic-level tests where possible, route-level for auth + shape
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Interest, SavedTrip, DismissedTrip, User
from app.services.user_repo import UserRepository
from app.services.audit import AuditLogger


# Resolve repo paths so the test can load fixture JSONs.
REPO_ROOT = Path(__file__).resolve().parents[2]
EVENTS_PATH = REPO_ROOT / "data" / "events.json"
FLIGHTS_PATH = REPO_ROOT / "data" / "flights.json"


# ─── Local fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
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
    repo = UserRepository(db_session)
    user = await repo.create_user(
        email="sir@example.com",
        password="correct-horse-battery-staple",
        display_name="Sir",
    )
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def user_with_interests(db_session, seeded_user):
    """User with three interests: F1, indie/jazz, and design.

    Interest keywords are chosen to produce real intersections against
    the data/events.json catalog (notably Madrid F1 + El Clásico,
    Montreux Jazz, Boom Tomorrowland, Barcelona Primavera Sound, etc.).
    These match what a Travel Scout user would actually type in the
    onboarding flow — the /find endpoint must surface real candidates
    for real interest phrases.
    """
    interests = [
        Interest(
            user_id=seeded_user.id,
            name="F1 races",
            event_keywords="f1 motorsport",
            priority=0,
            active=True,
            notification_channels=[],
            date_flexibility="plusminus7",
        ),
        Interest(
            user_id=seeded_user.id,
            name="Live music & festivals",
            event_keywords="music_festival jazz edm indie hip_hop",
            priority=1,
            active=True,
            notification_channels=[],
            date_flexibility="plusminus3",
        ),
        Interest(
            user_id=seeded_user.id,
            name="Football",
            event_keywords="football sport el_clasico uefa",
            priority=2,
            active=True,
            notification_channels=[],
            date_flexibility="plusminus7",
        ),
    ]
    for i in interests:
        db_session.add(i)
    await db_session.commit()
    for i in interests:
        await db_session.refresh(i)
    return seeded_user, interests


@pytest_asyncio.fixture
async def app_client(db_session, user_with_interests):
    """Minimal FastAPI app with itineraries + account routers + dependency overrides.

    Includes the account router so tests that read /api/account/audit
    (after a save/dismiss) can verify audit_log rows were written.
    """
    from app.routers.itineraries import router as itineraries_router
    from app.routers.account import router as account_router
    from app.routers.auth import get_current_user
    from app.database import get_db

    user, interests = user_with_interests
    app = FastAPI()
    app.include_router(itineraries_router)
    app.include_router(account_router)

    async def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    async def _override_get_current_user():
        return user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    client = TestClient(app)
    yield client, user, interests
    app.dependency_overrides.clear()


# ─── POST /api/itineraries/find ───────────────────────────────────────────


def test_find_requires_auth():
    """POST /api/itineraries/find without auth → 401."""
    from app.routers.itineraries import router as itineraries_router
    app = FastAPI()
    app.include_router(itineraries_router)
    client = TestClient(app)
    r = client.post("/api/itineraries/find", json={})
    assert r.status_code == 401


def test_find_requires_at_least_two_interests(app_client):
    """User with 0 or 1 interest → 400 with actionable message."""
    from app.routers.itineraries import router as itineraries_router
    from app.database import get_db
    from app.routers.auth import get_current_user
    from app.models import User, Interest
    from app.services.user_repo import UserRepository

    # Build a fresh user with only 1 interest
    import asyncio
    async def setup():
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        from app.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as session:
            repo = UserRepository(session)
            u = await repo.create_user(
                email="one-interest@example.com",
                password="x", display_name="One",
            )
            await session.commit()
            session.add(Interest(
                user_id=u.id, name="F1",
                event_keywords="f1", priority=0, active=True,
                notification_channels=[], date_flexibility="plusminus3",
            ))
            await session.commit()
            return u, session, engine
    user, session, engine = asyncio.run(setup())

    app = FastAPI()
    app.include_router(itineraries_router)

    async def _override_get_db():
        yield session

    async def _override_get_current_user():
        return user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    client = TestClient(app)
    r = client.post("/api/itineraries/find", json={})
    assert r.status_code == 400
    body = r.json()
    assert "2" in body["detail"] or "two" in body["detail"].lower()


def test_find_returns_ranked_candidates(app_client):
    """User with 3 interests → POST /find returns ranked candidates."""
    client, user, interests = app_client
    r = client.post("/api/itineraries/find", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "candidates" in body
    candidates = body["candidates"]
    assert isinstance(candidates, list)
    # Candidates should be ranked by score descending
    for i in range(len(candidates) - 1):
        assert candidates[i]["score"] >= candidates[i+1]["score"]


def test_find_response_shape(app_client):
    """Each candidate has the documented shape."""
    client, _, _ = app_client
    r = client.post("/api/itineraries/find", json={})
    assert r.status_code == 200
    body = r.json()
    if not body["candidates"]:
        pytest.skip("No candidates found — fixture data may have changed")
    cand = body["candidates"][0]
    # Required keys
    for key in ("id", "city", "country", "start_date", "end_date",
                "events", "interests", "score", "itinerary", "score_breakdown"):
        assert key in cand, f"Missing key: {key}"
    # Itinerary is either a dict (with flight) or null (no flight)
    assert cand["itinerary"] is None or isinstance(cand["itinerary"], dict)
    if cand["itinerary"]:
        for key in ("flight_price_usd", "flight_booking_url", "days",
                    "destination_airport"):
            assert key in cand["itinerary"]


def test_find_excludes_dismissed_intersections(app_client):
    """After dismissing a trip's id, /find excludes it."""
    client, user, _ = app_client
    # First find
    r1 = client.post("/api/itineraries/find", json={})
    assert r1.status_code == 200
    candidates = r1.json()["candidates"]
    if not candidates:
        pytest.skip("No candidates to dismiss — fixture data may have changed")
    dismissed_id = candidates[0]["id"]

    # Dismiss the first candidate
    r2 = client.post(f"/api/itineraries/{dismissed_id}/dismiss")
    assert r2.status_code in (200, 204), r2.text

    # Find again — should not include the dismissed id
    r3 = client.post("/api/itineraries/find", json={})
    assert r3.status_code == 200
    returned_ids = {c["id"] for c in r3.json()["candidates"]}
    assert dismissed_id not in returned_ids


# ─── POST /api/itineraries/{trip_id}/save ─────────────────────────────────


def test_save_persists_a_trip(app_client):
    """POST /api/itineraries/{id}/save with a snapshot stores a SavedTrip row."""
    from sqlalchemy import select
    from app.models import SavedTrip
    client, user, _ = app_client
    r = client.post("/api/itineraries/find", json={})
    assert r.status_code == 200
    candidates = r.json()["candidates"]
    if not candidates:
        pytest.skip("No candidates to save")
    # The router's v1 contract: client supplies the snapshot from /find.
    trip_id = candidates[0]["id"]
    snapshot = candidates[0]  # full candidate payload

    r2 = client.post(
        f"/api/itineraries/{trip_id}/save",
        json={"snapshot": snapshot},
    )
    assert r2.status_code in (200, 201), r2.text

    # Now GET /api/itineraries should return it
    r3 = client.get("/api/itineraries")
    assert r3.status_code == 200
    saved = r3.json()
    assert any(t["intersection_id"] == trip_id for t in saved), \
        f"Saved trip {trip_id} not found in {saved}"


def test_save_writes_audit_row(app_client):
    """Save writes an audit_log row (accountability)."""
    client, user, _ = app_client
    r = client.post("/api/itineraries/find", json={})
    candidates = r.json()["candidates"]
    if not candidates:
        pytest.skip("No candidates to save")
    trip_id = candidates[0]["id"]
    snapshot = candidates[0]
    r2 = client.post(
        f"/api/itineraries/{trip_id}/save",
        json={"snapshot": snapshot},
    )
    assert r2.status_code in (200, 201), r2.text

    # Read audit history
    r3 = client.get("/api/account/audit")
    assert r3.status_code == 200
    actions = [row["action"] for row in r3.json()]
    assert "trip.save" in actions


# ─── GET /api/itineraries ─────────────────────────────────────────────────


def test_list_empty_for_new_user():
    """Fresh user with no saves → empty list."""
    from app.routers.itineraries import router as itineraries_router
    from app.database import get_db
    from app.routers.auth import get_current_user
    from app.services.user_repo import UserRepository
    from app.models import Base
    import asyncio

    async def setup():
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as session:
            repo = UserRepository(session)
            u = await repo.create_user(
                email="new@example.com", password="x", display_name="New",
            )
            await session.commit()
            return u, session
    user, session = asyncio.run(setup())

    app = FastAPI()
    app.include_router(itineraries_router)

    async def _override_get_db():
        yield session

    async def _override_get_current_user():
        return user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    client = TestClient(app)

    r = client.get("/api/itineraries")
    assert r.status_code == 200
    assert r.json() == []


# ─── POST /api/itineraries/{trip_id}/dismiss ──────────────────────────────


def test_dismiss_writes_audit_row(app_client):
    """Dismiss writes an audit_log row (matches save's behavior)."""
    client, user, _ = app_client
    r = client.post("/api/itineraries/find", json={})
    candidates = r.json()["candidates"]
    if not candidates:
        pytest.skip("No candidates to dismiss")
    trip_id = candidates[0]["id"]
    r2 = client.post(f"/api/itineraries/{trip_id}/dismiss")
    assert r2.status_code in (200, 204), r2.text

    r3 = client.get("/api/account/audit")
    actions = [row["action"] for row in r3.json()]
    assert "trip.dismiss" in actions


def test_dismiss_idempotent(app_client):
    """Dismissing the same id twice is a no-op (no error)."""
    client, user, _ = app_client
    r = client.post("/api/itineraries/find", json={})
    candidates = r.json()["candidates"]
    if not candidates:
        pytest.skip("No candidates to dismiss")
    trip_id = candidates[0]["id"]
    r1 = client.post(f"/api/itineraries/{trip_id}/dismiss")
    r2 = client.post(f"/api/itineraries/{trip_id}/dismiss")
    # Both should succeed (idempotent)
    assert r1.status_code in (200, 204)
    assert r2.status_code in (200, 204)


# ─── /api/itineraries/{trip_id} GET ────────────────────────────────────────


def test_get_saved_trip_returns_full_payload(app_client):
    """GET /api/itineraries/{id} on a saved trip returns the full payload."""
    client, user, _ = app_client
    r = client.post("/api/itineraries/find", json={})
    candidates = r.json()["candidates"]
    if not candidates:
        pytest.skip("No candidates")
    trip_id = candidates[0]["id"]
    snapshot = candidates[0]
    client.post(
        f"/api/itineraries/{trip_id}/save",
        json={"snapshot": snapshot},
    )

    r2 = client.get(f"/api/itineraries/{trip_id}")
    assert r2.status_code == 200, r2.text
    trip = r2.json()
    assert trip["intersection_id"] == trip_id
    assert "snapshot_json" in trip
    # The snapshot should include the events so the user can review offline
    snapshot_data = trip["snapshot_json"]
    if isinstance(snapshot_data, str):
        snapshot_data = json.loads(snapshot_data)
    assert "events" in snapshot_data
    assert "score" in snapshot_data


def test_get_unsaved_trip_returns_404(app_client):
    """GET /api/itineraries/{id} for a trip that's never been saved → 404."""
    client, user, _ = app_client
    r = client.get("/api/itineraries/never-saved-id-xyz")
    assert r.status_code == 404