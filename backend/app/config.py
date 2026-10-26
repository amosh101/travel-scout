"""Centralised settings.

Rules (carried from v1 lessons):

- Every secret must have a placeholder in .env.example; no defaults baked in.
- JWT_SECRET_KEY has no fallback - startup fails fast if missing.
- DATABASE_URL uses asyncpg in prod, aiosqlite in tests.
- ADMIN_ALLOWED_CIDRS is Tailscale-only for admin routes.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    env: Literal["development", "staging", "production", "test"] = "development"
    log_level: str = "INFO"
    app_name: str = "travel-scout"

    # --- Backend ---
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    api_v1_prefix: str = "/api"
    cors_origins: str = "http://localhost:3000"

    # --- Auth ---
    jwt_secret_key: str = Field(...)
    jwt_algorithm: str = "HS256"
    jwt_access_token_minutes: int = 60 * 24

    # --- Database ---
    database_url: str
    database_url_sync: str
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Stripe ---
    stripe_secret_key: str = Field(...)
    stripe_webhook_secret: str = Field(...)

    # --- Third-party data sources ---
    # Empty/missing = client factory returns "not configured" error, never fake data.
    kiwi_api_key: str = ""
    ticketmaster_api_key: str = ""
    jolpica_api_key: str = ""

    # --- Transactional delivery (2026-10-21) ---
    # Email via SMTP; SMS via Twilio REST. Missing values = the channel
    # SKIPS HONESTLY (status 'skipped_not_configured'), never fakes
    # success. Globals by design: SMTP + international SMS.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""

    # Stripe price ids per subscription tier (Checkout hand-off).
    stripe_price_limited: str = ""
    stripe_price_unlimited: str = ""
    stripe_price_concierge: str = ""

    # --- Weekly digest scheduler ---
    digests_enabled: bool = True
    digest_window_days: int = 30
    digest_max_results: int = 3
    digest_check_interval_s: int = 300

    # --- Media (file attachments for chat messages, 2026-07-24) ---
    # Where MessageAttachment payloads land on disk. Created at startup
    # if missing. Per-tenant subdirectories are appended by the upload
    # route; the route also enforces the per-file size cap below.
    media_root: str = "/var/lib/travel-scout/media"
    media_max_bytes: int = 10 * 1024 * 1024  # 10 MB per attachment

    # --- Tailscale admin gate ---
    admin_allowed_cidrs: str = "100.64.0.0/10"

    # --- Frontend origin (Stripe success/return URLs) ---
    web_base_url: str = "http://100.91.143.50:3000"

    # --- Bootstrap admin (first-boot superadmin) ---
    # Set via env: BOOTSTRAP_ADMIN_EMAIL.
    # If set, the bootstrap_admin service ensures this email has the
    # superadmin role. If the user does not exist, it is created with
    # a generated password logged once at startup.
    # Leave empty in production once a real admin exists; the bootstrap
    # is idempotent and harmless to keep set.
    bootstrap_admin_email: str = ""

    @field_validator("jwt_secret_key", "stripe_secret_key", "stripe_webhook_secret")
    @classmethod
    def _no_placeholder(cls, v: str, info) -> str:
        placeholder_markers = ("replace_me", "change_me", "your_", "xxx", "todo")
        lower = v.lower()
        if any(m in lower for m in placeholder_markers):
            raise ValueError(
                f"{info.field_name} looks like a placeholder ({v!r}); "
                "set a real value in .env before booting."
            )
        return v

    @field_validator("cors_origins", "admin_allowed_cidrs", "bootstrap_admin_email")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def admin_cidr_list(self) -> list[str]:
        return [o.strip() for o in self.admin_allowed_cidrs.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
