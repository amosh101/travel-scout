"""Tests for the booking-agent chat-thread API (/api/messages).

Covers:
  - POST /api/messages    : user (concierge) + agent paths, free-tier 403,
                            is_summary flag, audit log
  - GET  /api/messages    : chronological order, since filter, ownership 404,
                            agent read-any
  - POST /api/messages/attachments : MIME allowlist, size cap, ownership
  - GET  /api/messages/attachments/{id} : auth-gated download
  - build_booking_summary  : the auto-generated confirm summary
"""
from __future__ import annotations

import io
import os
import tempfile
import uuid
from typing import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# Per-test SQLite file so each test gets a clean schema.
TEST_DB_FILE = f"./test_messages_{uuid.uuid4().hex}.db"
TEST_MEDIA_DIR = tempfile.mkdtemp(prefix="test_media_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_FILE}"
os.environ["DATABASE_URL_SYNC"] = f"sqlite:///{TEST_DB_FILE}"
os.environ["MEDIA_ROOT"] = TEST_MEDIA_DIR
os.environ["MEDIA_MAX_BYTES"] = str(1024 * 1024)  # 1 MB for tests

from app.config import get_settings  # noqa: E402
from app.database import (  # noqa: E402
    Base,
    dispose_engine,
    get_session_factory,
)
from app.main import create_app  # noqa: E402
import app.models  # noqa: E402,F401  -- registers models on Base.metadata
from app.models import (  # noqa: E402
    AuditLog,
    BookingsLog,
    Message,
    MessageAttachment,
    Role,
    SavedItinerary,
    SubscriptionTier,
    User,
    UserRole,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


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
            # Seed roles + permissions so the agent path works
            from app.services.seed import seed_all
            factory = get_session_factory()
            async with factory() as session:
                await seed_all(session)
                await session.commit()
            yield ac
        await dispose_engine()
    try:
        os.remove(TEST_DB_FILE)
    except FileNotFoundError:
        pass


async def _register_and_login(
    client: AsyncClient,
    email: str,
    password: str = "supersecret1",
    tier: SubscriptionTier = SubscriptionTier.FREE,
) -> tuple[str, User]:
    """Register a user, promote them to ``tier``, log them in, return
    (access_token, user_row). The user_row is fetched from the DB so
    the test can attach the agent role in a separate call."""
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
    token = r.json()["access_token"]

    factory = get_session_factory()
    async with factory() as session:
        user = (await session.execute(
            select(User).where(User.email == email)
        )).scalar_one()
        user.tier = tier
        await session.commit()
        # refresh to get the updated row
        await session.refresh(user)
    return token, user


async def _make_agent_user(
    client: AsyncClient, email: str = "agent@local.test"
) -> tuple[str, User]:
    """Register a user with the agent role granted. They bypass the
    concierge-tier guard via the agent.work permission."""
    token, user = await _register_and_login(
        client, email, tier=SubscriptionTier.FREE
    )
    factory = get_session_factory()
    async with factory() as session:
        role = (await session.execute(
            select(Role).where(Role.key == "agent")
        )).scalar_one()
        # Idempotent grant
        existing = (await session.execute(
            select(UserRole).where(
                UserRole.user_id == user.id,
                UserRole.role_id == role.id,
                UserRole.revoked_at.is_(None),
            )
        )).scalar_one_or_none()
        if existing is None:
            session.add(UserRole(
                user_id=user.id, role_id=role.id, granted_by=None
            ))
            await session.commit()
    return token, user


async def _make_saved_itinerary(user: User, *, title: str = "Test Trip") -> SavedItinerary:
    """Insert a SavedItinerary directly via the session. The user owns it."""
    from datetime import datetime, timezone, timedelta
    starts = datetime.now(timezone.utc) + timedelta(days=30)
    ends = starts + timedelta(days=7)
    saved = SavedItinerary(
        user_id=user.id,
        title=title,
        starts_at=starts,
        ends_at=ends,
        payload={"destination_name": "Maputo", "origin": "Beijing"},
    )
    factory = get_session_factory()
    async with factory() as session:
        session.add(saved)
        await session.commit()
        await session.refresh(saved)
    return saved


# -----------------------------------------------------------------------------
# POST /api/messages
# -----------------------------------------------------------------------------


async def test_post_message_free_tier_returns_403(client):
    """Free-tier user cannot post; they get a 403 pointing at the outbound link."""
    token, user = await _register_and_login(client, "free@local.test")
    saved = await _make_saved_itinerary(user)

    r = await client.post(
        "/api/messages",
        json={"itinerary_id": str(saved.id), "body": "Hi"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403, r.text
    assert "concierge" in r.json()["detail"].lower()


async def test_post_message_concierge_user_succeeds(client):
    """Concierge user can post; the message is stored with sender_role=user."""
    token, user = await _register_and_login(
        client, "concierge@local.test", tier=SubscriptionTier.CONCIERGE
    )
    saved = await _make_saved_itinerary(user)

    r = await client.post(
        "/api/messages",
        json={"itinerary_id": str(saved.id), "body": "Please confirm dates"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["sender_role"] == "user"
    assert body["body"] == "Please confirm dates"
    assert body["itinerary_id"] == str(saved.id)
    assert body["is_summary"] is False
    assert body["booking_id"] is None
    assert body["attachments"] == []


async def test_post_message_agent_with_summary(client):
    """Agent can post with is_summary=True and structured summary fields."""
    token, user = await _register_and_login(client, "owner@local.test")
    saved = await _make_saved_itinerary(user)
    agent_token, _ = await _make_agent_user(client)

    r = await client.post(
        "/api/messages",
        json={
            "itinerary_id": str(saved.id),
            "body": "Booking confirmed — see summary.",
            "is_summary": True,
            "summary_start_date": "2026-08-15",
            "summary_end_date": "2026-08-22",
            "summary_destination": "Maputo",
            "summary_passport_required": True,
            "summary_visa_required": False,
            "summary_visa_status": "not_required",
            "summary_notes": "Check in 15:00.",
        },
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["sender_role"] == "agent"
    assert body["is_summary"] is True

    # Audit log carries the summary fields
    factory = get_session_factory()
    async with factory() as session:
        log = (await session.execute(
            select(AuditLog).where(
                AuditLog.action == "message.post",
                AuditLog.target_id == body["id"],
            )
        )).scalar_one()
        assert log.metadata_json["is_summary"] is True
        assert log.metadata_json["summary"]["destination"] == "Maputo"


async def test_post_message_other_users_itinerary_returns_404(client):
    """A user cannot post to another user's itinerary."""
    _, user_a = await _register_and_login(client, "a@local.test")
    _, user_b = await _register_and_login(
        client, "b@local.test", tier=SubscriptionTier.CONCIERGE
    )
    saved = await _make_saved_itinerary(user_a)
    token_b, _ = await _register_and_login(
        client, "b2@local.test", tier=SubscriptionTier.CONCIERGE
    )

    r = await client.post(
        "/api/messages",
        json={"itinerary_id": str(saved.id), "body": "Hi"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code == 404, r.text


async def test_post_message_body_too_long(client):
    """Body length is bounded to 8000 chars."""
    token, user = await _register_and_login(
        client, "long@local.test", tier=SubscriptionTier.CONCIERGE
    )
    saved = await _make_saved_itinerary(user)

    r = await client.post(
        "/api/messages",
        json={"itinerary_id": str(saved.id), "body": "x" * 8001},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422, r.text


# -----------------------------------------------------------------------------
# GET /api/messages
# -----------------------------------------------------------------------------


async def test_get_messages_chronological(client):
    """GET returns messages in created_at ASC order."""
    token, user = await _register_and_login(
        client, "read@local.test", tier=SubscriptionTier.CONCIERGE
    )
    saved = await _make_saved_itinerary(user)

    for body in ["First", "Second", "Third"]:
        await client.post(
            "/api/messages",
            json={"itinerary_id": str(saved.id), "body": body},
            headers={"Authorization": f"Bearer {token}"},
        )

    r = await client.get(
        f"/api/messages?itinerary_id={saved.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [m["body"] for m in items] == ["First", "Second", "Third"]


async def test_get_messages_since_filter(client):
    """since= param only returns newer messages."""
    from datetime import datetime, timezone
    import asyncio

    token, user = await _register_and_login(
        client, "since@local.test", tier=SubscriptionTier.CONCIERGE
    )
    saved = await _make_saved_itinerary(user)

    for body in ["First", "Second", "Third"]:
        await client.post(
            "/api/messages",
            json={"itinerary_id": str(saved.id), "body": body},
            headers={"Authorization": f"Bearer {token}"},
        )

    # Pick the created_at of the "Second" message as our boundary
    r = await client.get(
        f"/api/messages?itinerary_id={saved.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    second_ts = items[1]["created_at"]

    r = await client.get(
        f"/api/messages?itinerary_id={saved.id}&since={second_ts}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    newer = r.json()["items"]
    # Only "Third" should be newer (since= is strict >)
    assert [m["body"] for m in newer] == ["Third"]


async def test_get_messages_other_user_404(client):
    """A user cannot read another user's thread (404, not 403, for opsec)."""
    _, user_a = await _register_and_login(client, "ga@local.test")
    saved = await _make_saved_itinerary(user_a)
    token_b, _ = await _register_and_login(
        client, "gb@local.test", tier=SubscriptionTier.CONCIERGE
    )

    r = await client.get(
        f"/api/messages?itinerary_id={saved.id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code == 404, r.text


async def test_get_messages_agent_can_read_any(client):
    """Agent can read any thread."""
    _, user = await _register_and_login(client, "owner3@local.test")
    saved = await _make_saved_itinerary(user)
    agent_token, _ = await _make_agent_user(client, email="agent2@local.test")

    r = await client.get(
        f"/api/messages?itinerary_id={saved.id}",
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert r.status_code == 200, r.text


async def test_get_messages_empty(client):
    """GET on a fresh itinerary returns an empty list (not 404)."""
    token, user = await _register_and_login(
        client, "empty@local.test", tier=SubscriptionTier.CONCIERGE
    )
    saved = await _make_saved_itinerary(user)

    r = await client.get(
        f"/api/messages?itinerary_id={saved.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []
    assert r.json()["total"] == 0


# -----------------------------------------------------------------------------
# Attachments
# -----------------------------------------------------------------------------


async def test_attachment_upload_and_download(client):
    """End-to-end: agent uploads a PDF, owner downloads it."""
    token, user = await _register_and_login(
        client, "att-owner@local.test", tier=SubscriptionTier.CONCIERGE
    )
    saved = await _make_saved_itinerary(user)
    agent_token, _ = await _make_agent_user(client, email="att-agent@local.test")

    # Post a message first (uploads require an existing message)
    r = await client.post(
        "/api/messages",
        json={"itinerary_id": str(saved.id), "body": "Passport attached"},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert r.status_code == 201
    msg_id = r.json()["id"]

    # Upload the attachment
    payload = b"%PDF-1.4 fake pdf content for tests"
    r = await client.post(
        "/api/messages/attachments",
        data={"message_id": msg_id, "kind": "passport_scan"},
        files={"file": ("passport.pdf", io.BytesIO(payload), "application/pdf")},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert r.status_code == 201, r.text
    att = r.json()
    assert att["filename"] == "passport.pdf"
    assert att["mime_type"] == "application/pdf"
    assert att["size_bytes"] == len(payload)
    assert att["kind"] == "passport_scan"
    assert att["download_url"].startswith("/api/messages/attachments/")

    # Owner downloads it
    r = await client.get(
        att["download_url"],
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.content == payload


async def test_attachment_upload_wrong_mime_rejected(client):
    """MIME types not in the allowlist return 415."""
    agent_token, _ = await _make_agent_user(client, email="att-mime@local.test")
    _, user = await _register_and_login(client, "att-mime-owner@local.test")
    saved = await _make_saved_itinerary(user)

    r = await client.post(
        "/api/messages",
        json={"itinerary_id": str(saved.id), "body": "x"},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    msg_id = r.json()["id"]

    r = await client.post(
        "/api/messages/attachments",
        data={"message_id": msg_id},
        files={"file": ("evil.exe", io.BytesIO(b"MZ\x90\x00"), "application/x-msdownload")},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert r.status_code == 415, r.text


async def test_attachment_upload_size_cap(client, monkeypatch):
    """Files larger than settings.media_max_bytes return 413."""
    # Patch the settings cap directly so the test isn't dependent on
    # env-var caching between the fixture's get_settings() call and
    # the actual upload route.
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "media_max_bytes", 1024 * 1024)  # 1 MB

    agent_token, _ = await _make_agent_user(client, email="att-size@local.test")
    _, user = await _register_and_login(client, "att-size-owner@local.test")
    saved = await _make_saved_itinerary(user)

    r = await client.post(
        "/api/messages",
        json={"itinerary_id": str(saved.id), "body": "x"},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    msg_id = r.json()["id"]

    # 2 MB exceeds the 1 MB cap
    big = b"\0" * (2 * 1024 * 1024)
    r = await client.post(
        "/api/messages/attachments",
        data={"message_id": msg_id},
        files={"file": ("big.pdf", io.BytesIO(big), "application/pdf")},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert r.status_code == 413, r.text


async def test_attachment_download_path_traversal_blocked(client):
    """The filename is sanitised — path traversal is stripped before storage."""
    agent_token, _ = await _make_agent_user(client, email="att-traverse@local.test")
    _, user = await _register_and_login(client, "att-traverse-owner@local.test")
    saved = await _make_saved_itinerary(user)

    r = await client.post(
        "/api/messages",
        json={"itinerary_id": str(saved.id), "body": "x"},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    msg_id = r.json()["id"]

    r = await client.post(
        "/api/messages/attachments",
        data={"message_id": msg_id},
        files={"file": ("../../etc/passwd", io.BytesIO(b"x"), "text/plain")},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert r.status_code == 201, r.text
    # Filename should NOT contain path separators or ..
    safe_name = r.json()["filename"]
    assert "/" not in safe_name
    assert ".." not in safe_name
    assert safe_name.endswith("passwd")


async def test_attachment_other_user_cannot_download(client):
    """A different user cannot download someone else's attachment."""
    agent_token, _ = await _make_agent_user(client, email="att-perm@local.test")
    _, user = await _register_and_login(client, "att-perm-owner@local.test")
    saved = await _make_saved_itinerary(user)

    r = await client.post(
        "/api/messages",
        json={"itinerary_id": str(saved.id), "body": "x"},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    msg_id = r.json()["id"]
    r = await client.post(
        "/api/messages/attachments",
        data={"message_id": msg_id},
        files={"file": ("visa.pdf", io.BytesIO(b"PDF"), "application/pdf")},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    att_id = r.json()["id"]

    # Register a stranger and try to download
    other_token, _ = await _register_and_login(
        client, "stranger@local.test", tier=SubscriptionTier.CONCIERGE
    )
    r = await client.get(
        f"/api/messages/attachments/{att_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert r.status_code == 404, r.text


# -----------------------------------------------------------------------------
# Booking summary builder (unit test)
# -----------------------------------------------------------------------------


async def test_build_booking_summary_includes_dates_and_visa():
    """The summary body contains the dates, the visa reminder, and the
    agent note. The audit_meta carries the structured fields."""
    from app.routers.messages import build_booking_summary
    from datetime import datetime, timezone, date

    saved = SavedItinerary(
        id=uuid.uuid4(),
        title="Beira trip",
        starts_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        ends_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
        payload={"destination_name": "Beira"},
    )
    booking = BookingsLog(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        itinerary_id=saved.id,
        status="confirmed",
        amount_cents=120000,
        currency="USD",
        external_id="BK-001",
    )
    user = User(
        id=uuid.uuid4(),
        email="x@y.test",
        password_hash="x",
        name="Test",
        passport_expiry=date(2027, 1, 1),
    )
    body, meta = build_booking_summary(
        booking=booking,
        saved=saved,
        user=user,
        outcome_note="Visa waived for SA passport holders",
        amount_cents=120000,
        currency="USD",
        external_id="BK-001",
    )
    assert "*Booking confirmed — Beira*" in body
    assert "2026-09-01" in body
    assert "2026-09-08" in body
    assert "1,200.00 USD" in body
    assert "BK-001" in body
    assert "passport expires" in body  # < 180d warning won't fire; user has 7+ months
    assert "Visa waived for SA passport holders" in body

    assert meta["destination"] == "Beira"
    assert meta["amount_cents"] == 120000
    assert meta["external_id"] == "BK-001"
    assert meta["passport_expiry"] == "2027-01-01"


async def test_build_booking_summary_flags_short_passport():
    """A passport expiring in <180 days triggers the renew warning."""
    from app.routers.messages import build_booking_summary
    from datetime import date, timedelta, datetime, timezone

    soon = date.today() + timedelta(days=90)
    user = User(
        id=uuid.uuid4(), email="x@y.test", password_hash="x", name="T",
        passport_expiry=soon,
    )
    saved = SavedItinerary(
        id=uuid.uuid4(), title="Trip",
        starts_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        ends_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
        payload={"destination_name": "Beira"},
    )
    booking = BookingsLog(
        id=uuid.uuid4(), user_id=user.id, itinerary_id=saved.id,
        status="confirmed", amount_cents=0, currency="USD",
    )
    body, _ = build_booking_summary(
        booking=booking, saved=saved, user=user,
        outcome_note=None, amount_cents=None, currency=None, external_id=None,
    )
    assert "passport expires in 90 days" in body
    assert "Renew before travel" in body