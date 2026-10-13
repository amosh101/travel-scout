"""
Tests for the AuditLogger service.

TDD discipline: these tests were written BEFORE the AuditLogger implementation.
The service (app.services.audit.AuditLogger) must:
  - record(): write one audit_log row, flush (not commit), return the AuditLog.
  - query():  return rows filtered by user_id / action / since, ordered DESC
              by occurred_utc, capped at `limit`.

All tests use the in-memory SQLite `db_session` fixture from conftest.py.
"""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import AuditLog
from app.services.audit import AuditLogger


# All tests in this module are async.
pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_session():
    """Local in-memory SQLite session fixture.

    Mirrors the contract documented in backend/tests/conftest.py
    (clean per-test DB, Base.metadata.create_all/drop_all around the test).
    pytest-asyncio strict mode requires async fixtures to be decorated
    with @pytest_asyncio.fixture; this local copy satisfies that.
    """
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


# ---------------------------------------------------------------------------
# record() tests
# ---------------------------------------------------------------------------

async def test_record_writes_one_row(db_session):
    """record() persists exactly one audit_log row (visible after flush)."""
    logger = AuditLogger(db_session)

    await logger.record(action="test.event")

    await db_session.commit()
    count = (
        await db_session.execute(select(func.count(AuditLog.id)))
    ).scalar_one()
    assert count == 1, f"Expected 1 audit_log row, got {count}"


async def test_record_returns_audit_log_object(db_session):
    """The return value of record() is an AuditLog instance with the given action."""
    logger = AuditLogger(db_session)

    entry = await logger.record(action="user.signup")

    assert isinstance(entry, AuditLog), f"Expected AuditLog, got {type(entry)!r}"
    assert entry.action == "user.signup"
    assert entry.id is not None, "AuditLog.id should be auto-generated"


async def test_record_stores_user_id_when_provided(db_session):
    """record(user_id=...) stores the user_id on the row."""
    logger = AuditLogger(db_session)
    user_id = uuid4()

    await logger.record(action="user.login", user_id=user_id)
    await db_session.commit()

    rows = await logger.query(user_id=user_id)
    assert len(rows) == 1
    assert rows[0].user_id == user_id


async def test_record_defaults_source_to_api(db_session):
    """If source is not given, it defaults to 'api' on the stored row."""
    logger = AuditLogger(db_session)

    await logger.record(action="user.view")
    await db_session.commit()

    rows = await logger.query()
    assert len(rows) == 1
    assert rows[0].source == "api", f"Expected source='api', got {rows[0].source!r}"


async def test_record_stores_before_and_after_json(db_session):
    """before / after dicts are stored as JSON and round-trip cleanly."""
    logger = AuditLogger(db_session)
    before = {"price": 100, "currency": "USD"}
    after = {"price": 120, "currency": "USD"}

    await logger.record(
        action="alert.update",
        before=before,
        after=after,
    )
    await db_session.commit()

    rows = await logger.query(action="alert.update")
    assert len(rows) == 1
    # SA JSON column may return dict or JSON string depending on dialect;
    # SQLite returns the dict directly.
    stored_before = rows[0].before_json
    stored_after = rows[0].after_json
    if isinstance(stored_before, str):
        stored_before = json.loads(stored_before)
    if isinstance(stored_after, str):
        stored_after = json.loads(stored_after)
    assert stored_before == before
    assert stored_after == after


async def test_record_stores_request_id(db_session):
    """record(request_id='req-123') persists that request_id on the row."""
    logger = AuditLogger(db_session)

    await logger.record(action="api.call", request_id="req-123")
    await db_session.commit()

    rows = await logger.query(action="api.call")
    assert len(rows) == 1
    assert rows[0].request_id == "req-123"


async def test_record_with_minimal_args_only_action(db_session):
    """record() works with action as the sole argument — all other fields optional."""
    logger = AuditLogger(db_session)

    entry = await logger.record(action="test.event")

    await db_session.commit()
    assert entry.action == "test.event"
    assert entry.user_id is None
    assert entry.target_type is None
    assert entry.target_id is None
    assert entry.before_json is None
    assert entry.after_json is None
    assert entry.source == "api"
    assert entry.ip_address is None
    assert entry.request_id is None


# ---------------------------------------------------------------------------
# query() tests
# ---------------------------------------------------------------------------

async def test_query_filters_by_user_id(db_session):
    """query(user_id=...) returns only rows belonging to that user."""
    logger = AuditLogger(db_session)
    user_a = uuid4()
    user_b = uuid4()

    await logger.record(action="user.login", user_id=user_a)
    await logger.record(action="user.view",  user_id=user_a)
    await logger.record(action="user.login", user_id=user_b)
    await db_session.commit()

    rows_a = await logger.query(user_id=user_a)
    rows_b = await logger.query(user_id=user_b)

    assert len(rows_a) == 2, f"Expected 2 rows for user_a, got {len(rows_a)}"
    assert len(rows_b) == 1, f"Expected 1 row for user_b, got {len(rows_b)}"
    assert all(r.user_id == user_a for r in rows_a)


async def test_query_filters_by_action(db_session):
    """query(action=...) returns only rows matching that action."""
    logger = AuditLogger(db_session)

    await logger.record(action="user.signup")
    await logger.record(action="user.login")
    await logger.record(action="user.login")
    await db_session.commit()

    signup_rows = await logger.query(action="user.signup")
    login_rows = await logger.query(action="user.login")

    assert len(signup_rows) == 1
    assert signup_rows[0].action == "user.signup"
    assert len(login_rows) == 2


async def test_query_filters_by_since(db_session):
    """query(since=T) returns only rows with occurred_utc >= T."""
    logger = AuditLogger(db_session)
    # Anchor to a known UTC instant; subsequent rows will use utcnow which is later.
    t1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    t2 = t1 + timedelta(hours=1)
    t3 = t1 + timedelta(hours=2)

    # Insert one row at t1 (by overriding occurred_utc via a direct ORM write).
    entry_old = AuditLog(action="event.old", occurred_utc=t1)
    db_session.add(entry_old)
    await db_session.flush()

    # Insert a second row at t2 (also explicit).
    entry_mid = AuditLog(action="event.mid", occurred_utc=t2)
    db_session.add(entry_mid)
    await db_session.flush()

    # Insert a third row at t3.
    entry_new = AuditLog(action="event.new", occurred_utc=t3)
    db_session.add(entry_new)
    await db_session.commit()

    # since=t2 → only t2 and t3 should match (inclusive).
    rows = await logger.query(since=t2)
    assert len(rows) == 2, f"Expected 2 rows since t2, got {len(rows)}"
    timestamps = {r.occurred_utc for r in rows}
    assert t2 in timestamps
    assert t3 in timestamps
    assert t1 not in timestamps


async def test_query_orders_by_occurred_utc_desc(db_session):
    """query() returns rows ordered by occurred_utc DESC (newest first)."""
    logger = AuditLogger(db_session)
    t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc)

    db_session.add(AuditLog(action="event.first",  occurred_utc=t1))
    db_session.add(AuditLog(action="event.second", occurred_utc=t2))
    await db_session.commit()

    rows = await logger.query()
    assert len(rows) == 2
    assert rows[0].action == "event.second", (
        "Newest row should come first when ordered by occurred_utc DESC"
    )
    assert rows[1].action == "event.first"


async def test_query_respects_limit(db_session):
    """query(limit=N) returns at most N rows even when more exist."""
    logger = AuditLogger(db_session)

    for i in range(5):
        await logger.record(action=f"event.{i}")
    await db_session.commit()

    rows = await logger.query(limit=2)
    assert len(rows) == 2, f"Expected 2 rows with limit=2, got {len(rows)}"