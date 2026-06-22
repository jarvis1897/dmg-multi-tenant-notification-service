from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "sqlite+aiosqlite:///./notifications.db"

    # Auth
    secret_key: str = "change-me-in-production-use-a-long-random-string"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours

    # Worker
    dispatch_poll_interval_seconds: int = 5
    worker_concurrency: int = 20  # asyncio.Semaphore size

    # Retry
    max_delivery_attempts: int = 3
    retry_backoff_base_seconds: float = 2.0
    retry_backoff_max_seconds: float = 300.0

    # Rate limits (requests per minute; overridable per tenant)
    default_rate_limit_email: int = 100
    default_rate_limit_sms: int = 50
    default_rate_limit_push: int = 200
    default_rate_limit_in_app: int = 500


settings = Settings()
