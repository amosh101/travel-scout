from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://travel_scout:travel_scout_dev@localhost:5432/travel_scout"

    # JWT
    JWT_SECRET_KEY: str = "dev-secret-key-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_API_URL: str = "https://api.telegram.org"

    # Email (Resend)
    RESEND_API_KEY: str = ""

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # App
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = True


settings = Settings()