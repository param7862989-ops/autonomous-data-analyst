"""Typed application settings loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Root .env (shared with Docker Compose) first; backend/.env overrides it if present.
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- General -------------------------------------------------------------------------
    environment: Environment = "development"
    app_name: str = "Autonomous Data Analyst"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    enable_api_docs: bool = True

    # --- HTTP ----------------------------------------------------------------------------
    # Browser origins of the frontend. Used for CORS and for the Origin check on state-changing
    # requests (CSRF defence). The Next.js server proxies /api/*, so browsers send its origin.
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # --- Database ------------------------------------------------------------------------
    database_url: str = "postgresql+psycopg://ada@localhost:5432/ada"
    database_pool_size: int = Field(default=5, ge=1, le=50)
    # Server-side cap on any single application query (milliseconds).
    database_statement_timeout_ms: int = Field(default=15_000, ge=100)

    # --- Auth ----------------------------------------------------------------------------
    allow_registration: bool = True
    session_cookie_name: str = "ada_session"
    # Absolute lifetime and inactivity timeout of a login session.
    session_ttl_hours: int = Field(default=24 * 7, ge=1)
    session_idle_timeout_hours: int = Field(default=24, ge=1)
    # None = Secure cookies in production only. Browsers treat http://localhost as secure.
    cookie_secure: bool | None = None
    # Requests per window, per client IP / per account.
    login_attempts_per_ip_per_minute: int = Field(default=20, ge=1)
    login_attempts_per_account_per_15_minutes: int = Field(default=10, ge=1)
    registrations_per_ip_per_hour: int = Field(default=10, ge=1)

    # --- Storage -------------------------------------------------------------------------
    storage_dir: Path = Path("storage")

    # --- Requests and uploads ------------------------------------------------------------
    # Hard cap on any non-upload request body (JSON).
    max_request_body_bytes: int = Field(default=1024 * 1024, ge=1024)
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    max_dataset_rows: int = Field(default=500_000, ge=1)
    max_dataset_columns: int = Field(default=200, ge=1)
    max_dataset_cells: int = Field(default=10_000_000, ge=1)
    # Zip-bomb guard for .xlsx: total uncompressed size of the archive.
    max_xlsx_uncompressed_bytes: int = Field(default=250 * 1024 * 1024, ge=1024)
    max_datasets_per_user: int = Field(default=100, ge=1)
    uploads_per_user_per_hour: int = Field(default=30, ge=1)
    # Parsing is memory-heavy; bound how many uploads are processed at once per process.
    max_concurrent_ingestions: int = Field(default=2, ge=1)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if self.environment != "production":
            return self
        if "*" in self.allowed_origins:
            raise ValueError("ALLOWED_ORIGINS must not contain '*' in production")
        if self.cookie_secure is False:
            raise ValueError("COOKIE_SECURE cannot be false in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def secure_cookies(self) -> bool:
        return self.is_production if self.cookie_secure is None else self.cookie_secure


@lru_cache
def get_settings() -> Settings:
    return Settings()
