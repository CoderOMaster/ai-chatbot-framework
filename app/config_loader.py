"""Configuration loader module - handles environment-based config loading."""
import os
from typing import Type

from pydantic import BaseModel, ValidationError, Field


class BaseConfig(BaseModel):
    """Base configuration with common settings."""

    DEBUG: bool = False
    Development: bool = False

    MONGODB_HOST: str = "mongodb://127.0.0.1:27017"
    MONGODB_DATABASE: str = "ai-chatbot-framework"

    MODELS_DIR: str = "model_files/"
    DEFAULT_FALLBACK_INTENT_NAME: str = "fallback"
    DEFAULT_WELCOME_INTENT_NAME: str = "init_conversation"
    SPACY_LANG_MODEL: str = "en_core_web_md"
    
    # API Gateway settings
    SERVICE_TIMEOUT: int = 30
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["*"])
    ALLOWED_HOSTS: list[str] = Field(default_factory=lambda: ["*"])
    ADMIN_SERVICE_URL: str = "http://admin-service:8001"
    BOT_SERVICE_URL: str = "http://bot-service:8002"
    DIALOGUE_SERVICE_URL: str = "http://dialogue-service:8003"

    class Config:
        """Pydantic config."""

        extra = "allow"


class DevelopmentConfig(BaseConfig):
    """Development environment configuration."""

    DEBUG: bool = True
    Development: bool = True
    TEMPLATES_AUTO_RELOAD: bool = True
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["*"])


class StagingConfig(BaseConfig):
    """Staging environment configuration."""

    DEBUG: bool = False
    Development: bool = False


class ProductionConfig(BaseConfig):
    """Production environment configuration."""

    SPACY_LANG_MODEL: str = "en_core_web_lg"
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["https://example.com"])


# Environment to config class mapping
CONFIG_MAP: dict[str, Type[BaseConfig]] = {
    "development": DevelopmentConfig,
    "staging": StagingConfig,
    "production": ProductionConfig,
}

# Required environment variables for validation
REQUIRED_ENV_VARS: list[str] = [
    "MONGODB_HOST",
    "MONGODB_DATABASE",
]


def validate_required_env_vars() -> None:
    """Validate that all required environment variables are set.

    Raises:
        ValueError: If any required environment variable is missing.
    """
    missing_vars = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
    if missing_vars:
        msg = f"Missing required environment variables: {', '.join(missing_vars)}"
        raise ValueError(msg)


def load_config() -> BaseConfig:
    """Load configuration from environment variables.

    Returns:
        BaseConfig: Configuration instance for the current environment.

    Raises:
        ValueError: If APPLICATION_ENV is invalid or required vars are missing.
        ValidationError: If environment variables fail Pydantic validation.
    """
    env_name = os.environ.get("APPLICATION_ENV", "development").lower()

    if env_name not in CONFIG_MAP:
        msg = (
            f"APPLICATION_ENV={env_name} is not valid, "
            f"must be one of {set(CONFIG_MAP.keys())}"
        )
        raise ValueError(msg)

    config_class = CONFIG_MAP[env_name]

    try:
        loaded_config = config_class(**os.environ)
    except ValidationError as e:
        msg = f"Configuration validation failed: {e}"
        raise ValueError(msg) from e

    return loaded_config