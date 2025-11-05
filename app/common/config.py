"""
Centralized settings for the project.

This module exposes a pydantic.BaseSettings Settings class so configuration
can be loaded from environment variables and .env files during local
development.

Usage:
    from app.common.config import Settings, get_settings
    settings = get_settings()

Keep backwards-compatibility by providing a lightweight `get_settings()`
helper and by ensuring the class is importable from the package root.
"""
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field, BaseModel # Import Field from pydantic


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Add any project-wide configuration values here. Fields defined here
    should be considered part of the public contract of the shared package
    and should follow semantic versioning when changed.
    """

    # Database
    # MONGODB_HOST may be a simple host ("localhost") or a full URI
    MONGODB_HOST: str = Field("localhost", description="MongoDB host or full URI")
    MONGODB_DATABASE: str = Field("ai_chatbot", description="MongoDB DB name")
    MONGODB_USERNAME: Optional[str] = Field(None, description="Optional MongoDB username")
    MONGODB_PASSWORD: Optional[str] = Field(None, description="Optional MongoDB password")
    MONGODB_MAX_POOL_SIZE: int = Field(100, description="MongoDB driver max pool size")
    MONGODB_CONNECT_TIMEOUT_MS: Optional[int] = Field(
        20000, description="MongoDB connect timeout in milliseconds"
    )
    MONGODB_SERVER_SELECTION_TIMEOUT_MS: Optional[int] = Field(
        30000, description="MongoDB server selection timeout in milliseconds"
    )

    # Healthcheck / retry
    MONGODB_HEALTHCHECK_RETRIES: int = Field(2, description="Number of healthcheck retries")
    MONGODB_HEALTHCHECK_BACKOFF_FACTOR: float = Field(
        0.5, description="Exponential backoff base for healthcheck retry in seconds"
    )

    # Security
    JWT_SECRET: str = Field("changeme", description="JWT signing secret")

    # Models and runtime
    MODELS_DIR: str = Field("models", description="Directory where NLU models live")
    DEFAULT_FALLBACK_INTENT_NAME: str = Field("fallback", description="Fallback intent id/name")

    # Optional third-party keys
    LLM_API_KEY: Optional[str] = Field(None, description="Optional LLM provider API key")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# simple module-level cache to avoid re-parsing env repeatedly
_settings_singleton: Optional[Settings] = None


def get_settings() -> Settings:
    """Return a cached Settings instance (reads environment on first call).

    This helper is convenient for places that want a singleton-style access
    while allowing tests to create their own Settings instances.
    """
    global _settings_singleton
    if _settings_singleton is None:
        _settings_singleton = Settings()
    return _settings_singleton


__all__ = ["Settings", "get_settings"]