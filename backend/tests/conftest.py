"""
Shared pytest fixtures for travel-scout backend tests.

All tests use an in-memory SQLite database by default for speed. Logic-level
tests mock the AsyncSession directly (no DB). DB-level tests use the
`db_session` fixture from this file.
"""

import sys
import asyncio
from pathlib import Path

# Ensure backend dir is on sys.path so `app.*` imports resolve
BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool


@pytest.fixture
def anyio_backend():
    """Use asyncio only (no trio support needed)."""
    return "asyncio"


@pytest_asyncio.fixture
async def db_session():
    """Provide a clean in-memory SQLite session per test.

    Uses StaticPool so the in-memory DB persists across connections within
    a test. Creates all tables from Base.metadata. Drops them at teardown.
    """
    from app.models import Base  # imported here to avoid circular issues

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


@pytest.fixture
def test_user():
    """A reusable mock user matching the SQLAlchemy User model."""
    from uuid import uuid4

    class FakeUser:
        def __init__(self):
            self.id = uuid4()
            self.email = "test@example.com"
            self.password_hash = "$2b$12$dummy"  # bcrypt format
            self.name = "Test User"
            self.phone = None
            self.telegram_chat_id = None
            self.whatsapp_phone = None
            self.created_at = None
            self.is_active = True

    return FakeUser()