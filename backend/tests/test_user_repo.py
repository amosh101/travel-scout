"""
Tests for the UserRepository service.

TDD discipline: these tests were written BEFORE the UserRepository implementation.
The service (app.services.user_repo.UserRepository) must:
  - create_user():        hash password (bcrypt), lowercase email, raise on duplicate.
  - get_by_email():       case-insensitive lookup, None if missing.
  - get_by_id():          lookup by UUID, None if missing.
  - verify_password():    True if password matches hash, False otherwise.
  - update_last_login():  no-op for now (User model lacks the column).
  - soft_delete_account(): GDPR right-to-erasure: is_active=False, PII cleared,
                           password_hash preserved so email can't be re-registered.
  - export_account_data(): JSON-serializable dict with user + interests + alerts +
                           saved_trips + dismissed_trips + audit_log.

All tests use the in-memory SQLite `db_session` fixture from conftest.py.

Note: tests that need their own async db_session fixture redefine it locally
(matching the test_audit.py pattern) because pytest-asyncio strict mode
requires @pytest_asyncio.fixture for async fixtures.
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import User, Interest, FlightAlert, SavedTrip, DismissedTrip, AuditLog
from app.services.user_repo import UserRepository


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
# create_user() tests
# ---------------------------------------------------------------------------

async def test_create_user_hashes_password(db_session):
    """create_user stores a bcrypt hash; verify_password round-trips correctly."""
    repo = UserRepository(db_session)

    user = await repo.create_user(email="alice@example.com", password="hunter2")

    assert await repo.verify_password(user, "hunter2") is True
    assert await repo.verify_password(user, "wrong-password") is False
    # Hash is not the plaintext
    assert user.password_hash != "hunter2"
    # Hash is a bcrypt hash ($2a$ / $2b$ / $2y$)
    assert user.password_hash.startswith(("$2a$", "$2b$", "$2y$"))


async def test_create_user_lowercases_email(db_session):
    """Mixed-case email is stored lowercased."""
    repo = UserRepository(db_session)

    await repo.create_user(email="Foo@Bar.com", password="hunter2")

    found = await repo.get_by_email("Foo@Bar.com")
    assert found is not None
    assert found.email == "foo@bar.com"


async def test_create_user_duplicate_email_raises(db_session):
    """A second create_user with the same email raises IntegrityError."""
    from sqlalchemy.exc import IntegrityError as SAIntegrityError

    repo = UserRepository(db_session)
    await repo.create_user(email="dup@example.com", password="hunter2")
    await db_session.commit()

    with pytest.raises((IntegrityError, SAIntegrityError)):
        await repo.create_user(email="dup@example.com", password="other")
        await db_session.commit()


async def test_create_user_truncates_long_password(db_session):
    """A 100-char password is hashed using its first 72 bytes; verify with the
    same 100-char password still returns True (bcrypt limitation: only the
    first 72 bytes matter)."""
    repo = UserRepository(db_session)
    long_pw = "a" * 100

    user = await repo.create_user(email="long@example.com", password=long_pw)

    assert await repo.verify_password(user, long_pw) is True


# ---------------------------------------------------------------------------
# get_by_email() tests
# ---------------------------------------------------------------------------

async def test_get_by_email_returns_none_when_missing(db_session):
    """get_by_email returns None for an email that hasn't been registered."""
    repo = UserRepository(db_session)

    result = await repo.get_by_email("none@example.com")

    assert result is None


async def test_get_by_email_is_case_insensitive(db_session):
    """get_by_email matches regardless of case."""
    repo = UserRepository(db_session)
    await repo.create_user(email="Foo@Bar.com", password="hunter2")
    await db_session.commit()

    found_lower = await repo.get_by_email("foo@bar.com")
    found_upper = await repo.get_by_email("FOO@BAR.COM")
    found_mixed = await repo.get_by_email("Foo@Bar.com")

    assert found_lower is not None
    assert found_upper is not None
    assert found_mixed is not None
    assert found_lower.id == found_upper.id == found_mixed.id


# ---------------------------------------------------------------------------
# get_by_id() tests
# ---------------------------------------------------------------------------

async def test_get_by_id_returns_user(db_session):
    """get_by_id returns the user with the matching UUID."""
    repo = UserRepository(db_session)
    user = await repo.create_user(email="bob@example.com", password="hunter2")
    await db_session.commit()

    found = await repo.get_by_id(user.id)

    assert found is not None
    assert found.id == user.id
    assert found.email == "bob@example.com"


async def test_get_by_id_returns_none_when_missing(db_session):
    """get_by_id returns None for a UUID that doesn't correspond to a user."""
    repo = UserRepository(db_session)

    result = await repo.get_by_id(uuid4())

    assert result is None


# ---------------------------------------------------------------------------
# soft_delete_account() tests
# ---------------------------------------------------------------------------

async def test_soft_delete_sets_is_active_false(db_session):
    """After soft_delete_account, the user has is_active=False."""
    repo = UserRepository(db_session)
    user = await repo.create_user(email="del@example.com", password="hunter2")
    await db_session.commit()

    await repo.soft_delete_account(user.id)
    await db_session.commit()

    found = await repo.get_by_id(user.id)
    assert found is not None
    assert found.is_active is False


async def test_soft_delete_clears_email(db_session):
    """After soft_delete_account, the original email no longer matches."""
    repo = UserRepository(db_session)
    user = await repo.create_user(email="erase@example.com", password="hunter2")
    await db_session.commit()

    await repo.soft_delete_account(user.id)
    await db_session.commit()

    found = await repo.get_by_email("erase@example.com")
    assert found is None, "Original email should not resolve after soft-delete"


async def test_soft_delete_clears_pii_fields(db_session):
    """After soft_delete_account, PII fields (name, phone) are cleared."""
    repo = UserRepository(db_session)
    user = await repo.create_user(
        email="pii@example.com",
        password="hunter2",
        display_name="Sensitive Name",
    )
    # Set the phone directly so we can verify it's cleared.
    user.phone = "+15551234567"
    user.telegram_chat_id = "tg-12345"
    user.whatsapp_phone = "+15559876543"
    await db_session.commit()

    await repo.soft_delete_account(user.id)
    await db_session.commit()

    found = await repo.get_by_id(user.id)
    assert found is not None
    assert found.name is None
    assert found.phone is None
    assert found.telegram_chat_id is None
    assert found.whatsapp_phone is None
    # Password hash preserved so the email can't be re-registered.
    assert found.password_hash is not None
    assert found.password_hash != ""


# ---------------------------------------------------------------------------
# export_account_data() tests
# ---------------------------------------------------------------------------

async def test_export_returns_user_dict(db_session):
    """export returns a dict containing a 'user' key with the user's email/name/etc."""
    repo = UserRepository(db_session)
    user = await repo.create_user(
        email="export@example.com",
        password="hunter2",
        display_name="Export User",
    )
    await db_session.commit()

    data = await repo.export_account_data(user.id)

    assert isinstance(data, dict)
    assert "user" in data
    assert data["user"]["email"] == "export@example.com"
    assert data["user"]["name"] == "Export User"
    assert data["user"]["id"] == str(user.id)


async def test_export_includes_interests(db_session):
    """export includes the user's interests."""
    repo = UserRepository(db_session)
    user = await repo.create_user(email="int@example.com", password="hunter2")

    interest = Interest(
        user_id=user.id,
        name="F1 races",
        origin_airport="LHR",
        destination_region="Europe",
        notification_channels=["email"],
        active=True,
        priority=0,
    )
    db_session.add(interest)
    await db_session.commit()

    data = await repo.export_account_data(user.id)

    assert "interests" in data
    assert isinstance(data["interests"], list)
    assert len(data["interests"]) == 1
    assert data["interests"][0]["name"] == "F1 races"


async def test_export_returns_empty_lists_for_no_relationships(db_session):
    """export works even when the user has no relationships — empty lists."""
    repo = UserRepository(db_session)
    user = await repo.create_user(email="solo@example.com", password="hunter2")
    await db_session.commit()

    data = await repo.export_account_data(user.id)

    assert isinstance(data, dict)
    assert data["user"]["email"] == "solo@example.com"
    # All relationship buckets are present (even if empty).
    for key in ("interests", "alerts", "saved_trips", "dismissed_trips", "audit_log"):
        assert key in data, f"Missing key {key!r} in export"
        assert data[key] == [], f"{key!r} should be an empty list"