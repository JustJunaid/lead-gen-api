"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "LeadGen API"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: Literal["development", "staging", "production"] = "development"

    # API
    api_v1_prefix: str = "/api/v1"
    api_key_header: str = "X-API-Key"

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://leadgen:leadgen_secret@localhost:5432/leadgen"
    )
    database_pool_size: int = 20
    database_max_overflow: int = 10
    database_echo: bool = False

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Celery
    celery_broker_url: str = Field(default="redis://localhost:6379/1")
    celery_result_backend: str = Field(default="redis://localhost:6379/2")

    # Scraping Providers
    rapidapi_key: SecretStr | None = None
    rapidapi_host: str = "fresh-linkedin-profile-data.p.rapidapi.com"
    brightdata_api_key: SecretStr | None = None
    brightdata_zone: str | None = None

    # Scraping Rate Limits
    scraping_default_rate_limit: int = 100  # per minute
    scraping_max_concurrent: int = 50
    scraping_retry_attempts: int = 3

    # Email Verification (MailTester.ninja)
    # Get your API key from: https://mailtester.ninja/
    mailtester_ninja_api_key: SecretStr | None = None
    email_verification_timeout: int = 10  # seconds

    # AI Providers (System defaults)
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    google_ai_api_key: SecretStr | None = None

    # AI Configuration
    ai_default_model: str = "gpt-4o-mini"
    ai_max_tokens: int = 2000
    ai_temperature: float = 0.7
    ai_requests_per_minute: int = 60

    # Import Configuration
    csv_import_chunk_size: int = 10000
    csv_max_file_size_mb: int = 500

    # Security
    secret_key: SecretStr = Field(default=SecretStr("change-me-in-production-min-32-chars"))
    api_key_salt: str = Field(default="change-me-salt")
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    # CORS
    cors_origins: list[str] = ["*"]
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure async driver is used."""
        if v and "postgresql://" in v and "asyncpg" not in v:
            return v.replace("postgresql://", "postgresql+asyncpg://")
        return v

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.environment == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
