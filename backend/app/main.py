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
from app.routers import admin_audit, billing


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting %s in %s mode", settings.app_name, settings.env)
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
    return app


app = create_app()