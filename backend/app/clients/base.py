"""Third-party client base: protocol + no-fake-data contract.

Every client in ``app.clients.*`` inherits from ``BaseClient`` and implements
``is_configured()`` + ``fetch_*()`` methods. If auth is missing, the factory
returns an instance whose ``fetch_*()`` raises ``NotConfiguredError`` — never
fake/seed data.
"""
from __future__ import annotations

from typing import Protocol


class NotConfiguredError(RuntimeError):
    """Raised when a client is called without its API key configured."""


class BaseClient(Protocol):
    """All clients expose ``source_key`` and an ``is_configured`` check."""

    source_key: str

    def is_configured(self) -> bool: ...


def require_configured(client: BaseClient) -> None:
    if not client.is_configured():
        raise NotConfiguredError(
            f"client {client.source_key!r} is not configured; "
            "set the matching env var to enable"
        )


__all__ = ["BaseClient", "NotConfiguredError", "require_configured"]