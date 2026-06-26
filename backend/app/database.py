from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


# MVP Revamp 2026-06-25: pool_size/max_overflow only apply to non-SQLite
# dialects (Postgres). SQLite uses a single connection per process so the
# pool args raise TypeError on import. Detect dialect from DATABASE_URL.
def _build_engine_kwargs(url: str | None = None):
    """Return engine kwargs appropriate for the configured DATABASE_URL dialect."""
    url = url or settings.DATABASE_URL
    if url.startswith("sqlite"):
        return {
            "echo": settings.DEBUG,
            "connect_args": {"check_same_thread": False},
        }
    # Postgres / MySQL / other
    return {
        "echo": settings.DEBUG,
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
    }


# Module-level engine + sessionmaker. These are intentionally rebindable so
# tests can swap them for an in-memory SQLite engine without leaving a
# cross-loop pool in place. Production code reads `async_session_maker`
# (the current module attribute) at call time, so rebinding takes effect
# immediately for `from app.database import async_session_maker` users too.
engine = create_async_engine(
    settings.DATABASE_URL,
    **_build_engine_kwargs(),
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    # Resolved at call time so test fixtures that rebind the module-level
    # `async_session_maker` are honoured by every Depends(get_db) consumer.
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    # Same: use the current `engine` attribute, not a captured reference.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def rebind_engine(url: str):
    """Swap the module-level engine + sessionmaker for one bound to `url`.

    The old engine is NOT disposed here — disposing an asyncpg/aiosqlite
    engine whose pool has connections bound to a closed event loop can hang
    the caller on graceful termination. Tests rebind on every setup and
    only ever need the new engine; the old one is replaced at the module
    attribute and left for GC. Production callers never call this.

    Returns the new engine so callers can run init_schema directly if needed.
    """
    global engine, async_session_maker

    engine = create_async_engine(url, **_build_engine_kwargs(url))
    async_session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine


async def restore_engine():
    """Restore the production engine bound to settings.DATABASE_URL.

    Test fixtures call this in teardown so subsequent tests start clean.
    """
    await rebind_engine(settings.DATABASE_URL)