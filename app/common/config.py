from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "sqlite+aiosqlite:///./notifications.db"

    # Auth
    secret_key: str = "change-me-in-production-use-a-long-random-string"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours

    # Dispatch engine
    poll_interval_seconds: int = 3
    worker_pool_size: int = 10

    # Retry
    max_attempts: int = 5
    base_backoff_seconds: float = 2.0
    max_backoff_seconds: float = 60.0
    retry_jitter_seconds: float = 1.0

    # Mocked provider
    simulate_failure_rate: float = 0.1

    # Rate limits (requests per minute; overridable per tenant)
    default_rate_limit_email: int = 100
    default_rate_limit_sms: int = 50
    default_rate_limit_push: int = 200
    default_rate_limit_in_app: int = 500


settings = Settings()
