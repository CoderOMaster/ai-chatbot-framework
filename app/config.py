"""
Configuration module for AI Chatbot Framework.

This module provides type-safe configuration management using Pydantic BaseSettings.
It validates required fields and supports environment-specific configurations.

Configuration is loaded from environment variables with the following precedence:
1. Environment variables (highest priority)
2. .env file
3. Default values (lowest priority)

Environment Variables:
    APPLICATION_ENV: Deployment environment (Development, Testing, Production)
    MONGODB_HOST: MongoDB connection string
    MONGODB_DATABASE: MongoDB database name
    MODELS_DIR: Directory path for model files
    SPACY_LANG_MODEL: SpaCy language model identifier
    DEBUG: Enable debug mode (boolean)
    TESTING: Enable testing mode (boolean)
"""

import os
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

# Load environment variables from .env file
load_dotenv()

# Environment variable name constants
ENV_APPLICATION_ENV = "APPLICATION_ENV"
ENV_DEBUG = "DEBUG"
ENV_DEVELOPMENT = "Development"
ENV_TESTING = "TESTING"
ENV_MONGODB_HOST = "MONGODB_HOST"
ENV_MONGODB_DATABASE = "MONGODB_DATABASE"
ENV_MODELS_DIR = "MODELS_DIR"
ENV_SPACY_LANG_MODEL = "SPACY_LANG_MODEL"
ENV_DEFAULT_FALLBACK_INTENT_NAME = "DEFAULT_FALLBACK_INTENT_NAME"
ENV_DEFAULT_WELCOME_INTENT_NAME = "DEFAULT_WELCOME_INTENT_NAME"
ENV_TEMPLATES_AUTO_RELOAD = "TEMPLATES_AUTO_RELOAD"


class BaseConfig(BaseSettings):
    """Base configuration with common settings for all environments."""

    model_config = {"env_file": ".env", "case_sensitive": True}

    # Environment and debug settings
    debug: bool = Field(default=False, description="Enable debug mode")
    development: bool = Field(default=False, description="Enable development mode")
    testing: bool = Field(default=False, description="Enable testing mode")
    templates_auto_reload: bool = Field(
        default=False, description="Auto-reload templates on file changes"
    )

    # MongoDB settings (required)
    mongodb_host: str = Field(
        default="mongodb://127.0.0.1:27017",
        description="MongoDB connection string",
    )
    mongodb_database: str = Field(
        default="ai-chatbot-framework",
        description="MongoDB database name",
    )

    # Model settings (required)
    models_dir: str = Field(
        default="model_files/",
        description="Directory path for model files",
    )
    spacy_lang_model: str = Field(
        default="en_core_web_md",
        description="SpaCy language model identifier",
    )

    # Intent settings
    default_fallback_intent_name: str = Field(
        default="fallback",
        description="Default fallback intent name",
    )
    default_welcome_intent_name: str = Field(
        default="init_conversation",
        description="Default welcome/init conversation intent name",
    )

    @field_validator("mongodb_host", "mongodb_database", "models_dir", "spacy_lang_model")
    @classmethod
    def validate_required_fields(cls, v: str) -> str:
        """Validate that required configuration fields are not empty."""
        if not v or not v.strip():
            raise ValueError("Required configuration field cannot be empty")
        return v.strip()

    @field_validator("models_dir")
    @classmethod
    def validate_models_dir(cls, v: str) -> str:
        """Validate that models directory path is valid."""
        if not v.endswith("/"):
            return v + "/"
        return v


class DevelopmentConfig(BaseConfig):
    """Configuration for development environment."""

    debug: bool = True
    development: bool = True
    templates_auto_reload: bool = True


class TestingConfig(BaseConfig):
    """Configuration for testing environment."""

    debug: bool = True
    testing: bool = True


class ProductionConfig(BaseConfig):
    """Configuration for production environment."""

    spacy_lang_model: str = "en_core_web_lg"


# Configuration registry mapping environment names to config classes
CONFIG_REGISTRY: dict[
    Literal["Development", "Testing", "Production"], type[BaseConfig]
] = {
    "Development": DevelopmentConfig,
    "Testing": TestingConfig,
    "Production": ProductionConfig,
}


def get_config() -> BaseConfig:
    """
    Load and return configuration based on APPLICATION_ENV environment variable.

    Returns:
        BaseConfig: Configuration instance for the specified environment.

    Raises:
        ValueError: If APPLICATION_ENV is not one of the valid options.
        ValidationError: If required configuration fields are missing or invalid.

    Examples:
        >>> config = get_config()
        >>> print(config.mongodb_host)
        >>> print(config.debug)
    """
    env_choice = os.environ.get(ENV_APPLICATION_ENV, "Development")

    if env_choice not in CONFIG_REGISTRY:
        valid_envs = set(CONFIG_REGISTRY.keys())
        raise ValueError(
            f"APPLICATION_ENV={env_choice} is not valid, must be one of {valid_envs}"
        )

    config_class = CONFIG_REGISTRY[env_choice]
    return config_class()


# Load configuration on module import
app_config = get_config()