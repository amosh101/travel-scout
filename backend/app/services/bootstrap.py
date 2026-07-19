"""First-boot setup: ensure a superadmin user exists.

Reads ``BOOTSTRAP_ADMIN_EMAIL`` from settings. If the user does not exist,
creates one with a generated password (printed to the log ONCE — sir's
"onboarding moment" pattern). If the user exists, just grants the
``superadmin`` role if not already present.

This is called from the FastAPI lifespan hook in ``main.py`` so the
first person to deploy this thing can log in and not get stuck behind
a chicken-and-egg admin wall.
"""
from __future__ import annotations

import logging
import secrets
import string

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Role, User, UserRole
from app.security import hash_password

logger = logging.getLogger(__name__)


def _generate_password(length: int = 20) -> str:
    """20-char password with letters, digits, and safe symbols (no shell-hostile chars)."""
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def bootstrap_admin(session: AsyncSession) -> dict | None:
    """Idempotent: ensure a superadmin user with the bootstrap email exists.

    Returns ``None`` if no bootstrap email is configured, or a dict with
    ``email`` and (if newly created) ``password`` for log output.
    """
    settings = get_settings()
    email = settings.bootstrap_admin_email
    if not email:
        return None

    superadmin = (await session.execute(
        select(Role).where(Role.key == "superadmin")
    )).scalar_one_or_none()
    if superadmin is None:
        logger.warning("bootstrap_admin: 'superadmin' role not seeded yet; skipping")
        return None

    user = (await session.execute(
        select(User).where(User.email == email)
    )).scalar_one_or_none()

    new_password: str | None = None
    if user is None:
        new_password = _generate_password()
        user = User(
            email=email,
            password_hash=hash_password(new_password),
            name="Bootstrap Admin",
            is_active=True,
        )
        session.add(user)
        await session.flush()
        logger.info("bootstrap_admin: created user %s (superadmin)", email)
    elif not user.is_active:
        user.is_active = True
        logger.info("bootstrap_admin: re-activated user %s", email)

    # Grant superadmin if not already active.
    existing_link = (await session.execute(
        select(UserRole).where(
            UserRole.user_id == user.id,
            UserRole.role_id == superadmin.id,
            UserRole.revoked_at.is_(None),
        )
    )).scalar_one_or_none()
    if existing_link is None:
        session.add(UserRole(user_id=user.id, role_id=superadmin.id))
        logger.info("bootstrap_admin: granted superadmin to %s", email)

    await session.commit()

    if new_password is not None:
        # The user MUST see this. The whole point of bootstrap is to give
        # the operator a one-shot password to log in with.
        logger.warning(
            "bootstrap_admin: NEW PASSWORD for %s = %s — store it, this is shown once",
            email, new_password,
        )
    return {"email": email, "newly_created": new_password is not None}
