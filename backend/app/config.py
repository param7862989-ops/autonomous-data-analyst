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
    # Origins allowed to call the API from a browser. The Next.js server proxies /api/* so the
    # browser normally talks to the API same-origin; this list only matters for direct calls.
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # --- Storage -------------------------------------------------------------------------
    storage_dir: Path = Path("storage")

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if self.environment == "production" and "*" in self.allowed_origins:
            raise ValueError("ALLOWED_ORIGINS must not contain '*' in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
