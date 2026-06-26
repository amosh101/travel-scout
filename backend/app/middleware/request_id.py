"""Request-ID middleware: attach a per-request UUID for tracing + audit.

The ID is:
- Generated at the start of every request.
- Stored in a contextvar so deep code paths (services, audit) can read it.
- Echoed back to the client as ``X-Request-Id`` for debugging.
- Stored on ``request.state`` for FastAPI routers.
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str | None:
    return _request_id_var.get()


class RequestIdMiddleware(BaseHTTPMiddleware):
    HEADER = "X-Request-Id"

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        rid = request.headers.get(self.HEADER) or str(uuid.uuid4())
        token = _request_id_var.set(rid)
        try:
            request.state.request_id = rid
            response = await call_next(request)
            response.headers[self.HEADER] = rid
            return response
        finally:
            _request_id_var.reset(token)