"""
Request-ID middleware for the travel-scout backend.

Each inbound request is tagged with an `X-Request-ID`:

  * If the client supplied one (case-insensitive), we reuse it (echoed back on
    the response) — this lets callers correlate logs across services.
  * Otherwise we generate a fresh ID. We prefer a ULID-style identifier but
    fall back to ``uuid.uuid4().hex`` so we don't have to add a new dependency
    just for this.

The id is:
  * attached to ``request.state.request_id`` so downstream route handlers and
    dependencies can include it in logs, error envelopes, and outbound calls;
  * written back to the response as the ``X-Request-ID`` header so the client
    sees the same value.

The middleware is defensive: if anything goes wrong it logs and continues
rather than raising, so observability tooling never breaks the request path.
"""

from __future__ import annotations

import logging
import uuid
from typing import Awaitable, Callable

from fastapi import Request, Response

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


def generate_request_id() -> str:
    """Generate a unique request ID.

    ULID-shaped preferred; ``uuid4().hex`` is fine when a ULID library isn't
    available (and adding one would cost a dependency just for this).
    """
    return uuid.uuid4().hex


def _extract_inbound_request_id(request: Request) -> str | None:
    """Pull X-Request-ID from inbound headers (case-insensitive).

    Starlette's ``Headers`` mapping is already case-insensitive, so a single
    lookup covers ``X-Request-ID``, ``x-request-id``, ``X-REQUEST-ID``, etc.
    """
    try:
        rid = request.headers.get(REQUEST_ID_HEADER)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to read X-Request-ID from inbound headers")
        return None
    if rid is None:
        return None
    rid = rid.strip()
    return rid or None


async def request_id_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """ASGI middleware that tags every request/response with an X-Request-ID."""
    try:
        rid = _extract_inbound_request_id(request) or generate_request_id()
        request.state.request_id = rid
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = rid
        return response
    except Exception:
        # Never let observability middleware break the request path.
        logger.exception("request_id_middleware failed; continuing without tag")
        return await call_next(request)
