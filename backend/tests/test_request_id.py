"""
Tests for the request_id middleware.

TDD discipline: these tests were written BEFORE the middleware implementation.
The middleware (app.middleware.request_id) must:
  1. Read X-Request-ID from inbound request headers (case-insensitive).
  2. If absent, generate a new ULID-style ID (uuid4().hex is acceptable).
  3. Attach the id to request.state.request_id.
  4. After the response is generated, set X-Request-ID on the response header.
  5. Never raise — if anything goes wrong, log it and continue.

Each test spins up its own minimal FastAPI app with the middleware installed,
so the tests are isolated from the production app wiring in app.main.
"""

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient


def _build_app_with_middleware(middleware_callable):
    """Helper: build a minimal FastAPI app wired with the given middleware."""
    app = FastAPI()
    app.add_middleware(__import__("starlette.middleware.base", fromlist=["BaseHTTPMiddleware"]).BaseHTTPMiddleware, dispatch=middleware_callable)

    @app.get("/ok")
    async def ok():
        return {"status": "ok"}

    @app.get("/boom")
    async def boom():
        raise HTTPException(status_code=418, detail="teapot")

    @app.get("/state")
    async def state(request: Request):
        return {"request_id": getattr(request.state, "request_id", None)}

    return app


# We import the middleware lazily so the FIRST test run (pre-implementation)
# reports real import failures rather than passing by accident.
def _import_middleware():
    from app.middleware.request_id import request_id_middleware  # noqa: WPS433
    return request_id_middleware


def test_middleware_module_exists():
    """The middleware package + module must be importable."""
    from app.middleware import request_id as mod  # noqa: F401

    assert hasattr(mod, "request_id_middleware"), (
        "app.middleware.request_id.request_id_middleware must exist"
    )


def test_middleware_generates_id_when_missing():
    """Request without X-Request-ID → response has X-Request-ID header with non-empty value."""
    request_id_middleware = _import_middleware()
    app = _build_app_with_middleware(request_id_middleware)
    client = TestClient(app)

    response = client.get("/ok")

    assert response.status_code == 200
    assert "x-request-id" in response.headers, (
        "Response must always include X-Request-ID header"
    )
    rid = response.headers["x-request-id"]
    assert isinstance(rid, str) and rid, "X-Request-ID must be a non-empty string"


def test_middleware_uses_inbound_header_when_present():
    """Request with X-Request-ID: foo123 → response X-Request-ID is foo123."""
    request_id_middleware = _import_middleware()
    app = _build_app_with_middleware(request_id_middleware)
    client = TestClient(app)

    response = client.get("/ok", headers={"X-Request-ID": "foo123"})

    assert response.status_code == 200
    assert response.headers.get("x-request-id") == "foo123", (
        "Inbound X-Request-ID must be echoed back verbatim"
    )


def test_middleware_attaches_to_request_state():
    """Route handler can read request.state.request_id and it matches the response header."""
    request_id_middleware = _import_middleware()
    app = _build_app_with_middleware(request_id_middleware)
    client = TestClient(app)

    response = client.get("/state", headers={"X-Request-ID": "abc-xyz-789"})

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "abc-xyz-789", (
        "request.state.request_id must equal the inbound header value"
    )
    assert response.headers["x-request-id"] == "abc-xyz-789", (
        "Response header must equal request.state.request_id"
    )
    assert body["request_id"] == response.headers["x-request-id"], (
        "State and response header must agree"
    )


def test_middleware_id_is_unique_across_requests():
    """Two requests with no inbound header get different IDs."""
    request_id_middleware = _import_middleware()
    app = _build_app_with_middleware(request_id_middleware)
    client = TestClient(app)

    r1 = client.get("/ok")
    r2 = client.get("/ok")

    rid1 = r1.headers["x-request-id"]
    rid2 = r2.headers["x-request-id"]

    assert rid1 and rid2, "Both responses must have non-empty X-Request-ID"
    assert rid1 != rid2, (
        f"Generated IDs must be unique across requests (got {rid1!r} twice)"
    )


def test_middleware_does_not_raise_on_route_error():
    """If the route raises an HTTPException, the response still has X-Request-ID."""
    request_id_middleware = _import_middleware()
    app = _build_app_with_middleware(request_id_middleware)
    client = TestClient(app)

    response = client.get("/boom", headers={"X-Request-ID": "err-trace-001"})

    assert response.status_code == 418, "The route's HTTPException must propagate"
    assert response.headers.get("x-request-id") == "err-trace-001", (
        "Middleware must still attach X-Request-ID even when the route errors"
    )
