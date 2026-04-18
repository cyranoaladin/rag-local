"""Application configuration and settings management."""
from __future__ import annotations

import secrets
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised runtime configuration for the dashboard backend."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    app_name: str = Field(default="rag-local dashboard API")
    environment: str = Field(default="development")

    database_url: str = Field(
        default="postgresql+psycopg://rag_local:rag_local@rag_db:5432/rag_local",
        alias="DATABASE_URL",
    )

    access_token_expire_minutes: int = Field(default=60 * 12, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    jwt_secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32), alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")

    cors_allow_origins: list[str] = Field(default_factory=list, alias="CORS_ALLOW_ORIGINS")

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()
