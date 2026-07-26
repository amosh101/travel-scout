"""FastAPI entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import dispose_engine
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.tailscale_gate import TailscaleAdminGate
from app.routers import (
    admin_audit,
    admin_sources,
    admin_users,
    admin_weights,
    agent,
    auth,
    billing,
    discover,
    itineraries,
    itineraries_discover,
    messages,
    profile,
    refdata,
    search,
)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting %s in %s mode", settings.app_name, settings.env)
    # Seed reference data (idempotent — re-runs are upserts).
    try:
        from app.database import get_session_factory
        from app.refdata.seed import seed_reference_data
        factory = get_session_factory()
        async with factory() as session:
            counts = await seed_reference_data(session)
            logger.info("refdata seeded: %s", counts)
    except Exception as exc:  # noqa: BLE001
        logger.exception("refdata seed failed (non-fatal): %s", exc)
    # Seed roles/permissions/tier limits/etc.
    try:
        from app.database import get_session_factory
        from app.services.seed import seed_all
        from app.services.bootstrap import bootstrap_admin
        factory = get_session_factory()
        async with factory() as session:
            counts = await seed_all(session)
            logger.info("reference seeded: %s", counts)
            await bootstrap_admin(session)
    except Exception as exc:  # noqa: BLE001
        logger.exception("reference seed failed (non-fatal): %s", exc)
    yield
    await dispose_engine()
    logger.info("Shut down %s", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Travel Scout API",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.env != "production" else None,
    )

    # Middleware order matters: request_id first (innermost), then CORS, then
    # admin gate at the edge.
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(TailscaleAdminGate)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.env, "version": app.version}

    app.include_router(billing.router, prefix=settings.api_v1_prefix)
    app.include_router(admin_audit.router, prefix=settings.api_v1_prefix)
    app.include_router(admin_users.router, prefix=settings.api_v1_prefix)
    app.include_router(admin_weights.router, prefix=settings.api_v1_prefix)
    app.include_router(admin_sources.router, prefix=settings.api_v1_prefix)
    app.include_router(agent.router, prefix=settings.api_v1_prefix)  # T8e
    app.include_router(messages.router, prefix=settings.api_v1_prefix)  # T8e-chat
    app.include_router(refdata.router, prefix=settings.api_v1_prefix)
    app.include_router(auth.router, prefix=settings.api_v1_prefix)
    app.include_router(profile.router, prefix=settings.api_v1_prefix)
    # itineraries_discover must be mounted BEFORE itineraries so the literal
    # /itineraries/discover route doesn't get swallowed by the
    # /itineraries/{itinerary_id} catch-all pattern.
    app.include_router(itineraries_discover.router, prefix=settings.api_v1_prefix)
    app.include_router(itineraries.router, prefix=settings.api_v1_prefix)
    app.include_router(search.router, prefix=settings.api_v1_prefix)
    app.include_router(discover.router, prefix=settings.api_v1_prefix)
    return app


app = create_app()