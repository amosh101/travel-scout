"""Security helpers: password hashing + JWT."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

# bcrypt has a 72-byte input cap; older passwords longer than that errored in v1.
# passlib handles truncation explicitly.
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__truncate_error=False)


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd.verify(plain, hashed)
    except Exception:
        return False


def create_access_token(
    subject: str,
    *,
    extra_claims: dict[str, Any] | None = None,
    expires_minutes: int | None = None,
) -> str:
    settings = get_settings()
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_access_token_minutes
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError(f"invalid token: {exc}") from exc


# -----------------------------------------------------------------------------
# T8f: passport-number obfuscation (NOT cryptographically secure)
# -----------------------------------------------------------------------------
# We XOR with a server-side key (the JWT secret) and base64 the result. This
# defeats trivial database-dump attacks (no plaintext PII in the row) but is
# NOT real encryption: anyone with the JWT secret can reverse it.
#
# Production replacement: switch to Fernet (cryptography.fernet.Fernet) with
# a dedicated key from env. Tracked as a v2.x follow-up.

import base64


def _obf_key() -> bytes:
    return get_settings().jwt_secret_key.encode("utf-8")[:32].ljust(32, b"0")


def obfuscate_passport(value: str) -> str:
    if not value:
        return value
    raw = value.encode("utf-8")
    key = _obf_key()
    xored = bytes((b ^ key[i % len(key)]) for i, b in enumerate(raw))
    return base64.urlsafe_b64encode(xored).decode("ascii")


def deobfuscate_passport(value: str) -> str:
    if not value:
        return value
    try:
        xored = base64.urlsafe_b64decode(value.encode("ascii"))
    except Exception:  # noqa: BLE001
        return ""  # not obfuscated, treat as empty
    key = _obf_key()
    return bytes((b ^ key[i % len(key)]) for i, b in enumerate(xored)).decode("utf-8", errors="replace")