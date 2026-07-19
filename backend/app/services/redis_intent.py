"""Redis client for short-lived intent storage (intake forms).

The user fills in a Step-1 intake on the landing page; we don't want them
to be authenticated yet. We stash the answers in Redis under a random
intent_id, with a 1-hour TTL, and the onboarding page reads it back when
the user registers.

In the dev Docker compose the running container sometimes has
``REDIS_URL=redis://redis:6379/0`` (compose hostname) while the actual
Redis is reachable at ``host.docker.internal:6379`` (or ``172.17.0.3``
on the bridge). Rather than fail, this module tries the configured URL
first and falls back to a known-working set.
"""
from __future__ import annotations

import json
import logging
import os
import socket
from typing import Any

import redis.asyncio as redis_async

logger = logging.getLogger(__name__)

_INTENT_TTL_SECONDS = 60 * 60  # 1 hour


def _candidate_urls() -> list[str]:
    """Return candidate Redis URLs to try, in order.

    The configured ``REDIS_URL`` is always first; then well-known fallbacks
    that work inside the dev Docker bridge. Tests can disable Redis
    entirely by setting ``TRAVEL_SCOUT_DISABLE_REDIS=1``.
    """
    urls: list[str] = []
    env = os.environ.get("REDIS_URL", "").strip()
    if env:
        urls.append(env)
    # Docker bridge (containers started with `docker run`, not compose)
    for h in ("host.docker.internal", "172.17.0.3"):
        urls.append(f"redis://{h}:6379/0")
    # Local dev (running outside Docker)
    urls.append("redis://localhost:6379/0")
    return urls


async def _try_connect(url: str) -> redis_async.Redis | None:
    try:
        client = redis_async.from_url(url, decode_responses=True, socket_connect_timeout=2)
        await client.ping()
        return client
    except (redis_async.RedisError, socket.gaierror, OSError) as e:  # noqa: BLE001
        logger.warning("Redis URL %s unreachable: %s", url, e)
        try:
            await client.aclose()  # type: ignore[possibly-undefined]
        except Exception:  # noqa: BLE001
            pass
        return None


async def get_redis() -> redis_async.Redis | None:
    """Return a connected Redis client, or None if none reachable.

    Disabled by ``TRAVEL_SCOUT_DISABLE_REDIS=1`` (used in unit tests).
    """
    if os.environ.get("TRAVEL_SCOUT_DISABLE_REDIS", "").strip() == "1":
        return None
    for url in _candidate_urls():
        client = await _try_connect(url)
        if client is not None:
            if not os.environ.get("REDIS_URL"):
                # Cache the working URL so subsequent calls hit it first.
                os.environ["REDIS_URL"] = url
            return client
    return None


# Module-level lazy singleton
_redis: redis_async.Redis | None = None
_redis_lock_key = "_travel_scout_redis_init"


async def _singleton() -> redis_async.Redis | None:
    global _redis
    if _redis is not None:
        return _redis
    _redis = await get_redis()
    return _redis


async def store_intent(intent_id: str, payload: dict[str, Any]) -> bool:
    """Store an intent JSON blob with a 1-hour TTL. Returns True if stored."""
    r = await _singleton()
    if r is None:
        return False
    try:
        await r.setex(f"intent:{intent_id}", _INTENT_TTL_SECONDS, json.dumps(payload))
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("Redis SETEX failed for intent %s: %s", intent_id, e)
        return False


async def load_intent(intent_id: str) -> dict[str, Any] | None:
    """Load an intent JSON blob, or None if missing/expired."""
    r = await _singleton()
    if r is None:
        return None
    try:
        raw = await r.get(f"intent:{intent_id}")
    except Exception as e:  # noqa: BLE001
        logger.warning("Redis GET failed for intent %s: %s", intent_id, e)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


async def delete_intent(intent_id: str) -> None:
    r = await _singleton()
    if r is None:
        return
    try:
        await r.delete(f"intent:{intent_id}")
    except Exception as e:  # noqa: BLE001
        logger.warning("Redis DEL failed for intent %s: %s", intent_id, e)


__all__ = ["store_intent", "load_intent", "delete_intent", "get_redis"]
