"""Tailscale-only admin gate.

Admin routes must come from Tailscale IPs. We resolve the client's effective IP
through ``X-Forwarded-For`` (set by Tailscale's subnet router) and match against
``ADMIN_ALLOWED_CIDRS`` in config. Non-admin routes pass through unchanged.
"""
from __future__ import annotations

import ipaddress
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings

_ADMIN_PREFIXES = ("/api/admin", "/admin")
# Agent-side endpoints live under /api/agent. The user-side handoff
# (POST /api/agent/queue to create a new row) is allowed from any
# origin (it just needs a JWT); the agent-side list/claim/release/
# outcome endpoints are Tailscale-only.
_AGENT_SIDE_METHOD_PREFIX = {
    "GET": ("/api/agent",),
    "PATCH": ("/api/agent",),
    "DELETE": ("/api/agent",),
}


class TailscaleAdminGate(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        method = request.method.upper()
        gated_prefixes: tuple[str, ...] = _ADMIN_PREFIXES
        if method in _AGENT_SIDE_METHOD_PREFIX:
            gated_prefixes = gated_prefixes + _AGENT_SIDE_METHOD_PREFIX[method]
        if not any(path.startswith(p) for p in gated_prefixes):
            return await call_next(request)

        settings = get_settings()
        client_ip = _resolve_client_ip(request)
        if client_ip is None or not _ip_in_any_cidr(client_ip, settings.admin_cidr_list):
            return Response(
                '{"error":"admin_routes_tailscale_only","client_ip":"%s"}' % (client_ip or "unknown"),
                status_code=403,
                media_type="application/json",
            )
        return await call_next(request)


def _resolve_client_ip(request: Request) -> str | None:
    """Best-effort client IP. Tailscale router sets X-Forwarded-For; else socket."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return None


def _ip_in_any_cidr(ip_str: str, cidrs: list[str]) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if ip in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False