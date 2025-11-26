"""
Application configuration using Pydantic BaseSettings.

This module provides environment-based configuration with support for
Development, Testing, and Production environments.
"""

import os
from typing import Literal
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    Supports environment-specific defaults for Development, Testing, and Production.
    """

    # Environment
    APPLICATION_ENV: Literal["Development", "Testing", "Production"] = Field(
        default="Development",
        description="Application environment"
    )
    DEBUG: bool = Field(
        default=False,
        description="Enable debug mode"
    )
    TESTING: bool = Field(
        default=False,
        description="Enable testing mode"
    )

    # MongoDB Configuration
    MONGODB_HOST: str = Field(
        default="mongodb://127.0.0.1:27017",
        description="MongoDB connection string"
    )
    MONGODB_DATABASE: str = Field(
        default="ai-chatbot-framework",
        description="MongoDB database name"
    )
    MONGODB_MAX_POOL_SIZE: int = Field(
        default=10,
        description="Maximum MongoDB connection pool size"
    )
    MONGODB_MIN_POOL_SIZE: int = Field(
        default=1,
        description="Minimum MongoDB connection pool size"
    )
    MONGODB_SOCKET_TIMEOUT_MS: int = Field(
        default=30000,
        description="MongoDB socket timeout in milliseconds"
    )
    MONGODB_CONNECT_TIMEOUT_MS: int = Field(
        default=10000,
        description="MongoDB connection timeout in milliseconds"
    )

    # Model Configuration
    MODELS_DIR: str = Field(
        default="model_files/",
        description="Directory containing ML models"
    )
    SPACY_LANG_MODEL: str = Field(
        default="en_core_web_md",
        description="Spacy language model to use"
    )

    # Intent Configuration
    DEFAULT_FALLBACK_INTENT_NAME: str = Field(
        default="fallback",
        description="Default fallback intent name"
    )
    DEFAULT_WELCOME_INTENT_NAME: str = Field(
        default="init_conversation",
        description="Default welcome intent name"
    )

    # Template Configuration
    TEMPLATES_AUTO_RELOAD: bool = Field(
        default=False,
        description="Enable automatic template reloading"
    )

    class Config:
        """Pydantic configuration."""
        env_file = ".env"
        case_sensitive = True

    def __init__(self, **data):
        """
        Initialize settings with environment-specific defaults.
        
        Applies default values based on APPLICATION_ENV before validation.
        """
        # Get environment first
        env = data.get("APPLICATION_ENV") or os.environ.get("APPLICATION_ENV", "Development")
        
        # Apply environment-specific defaults
        if env == "Development":
            data.setdefault("DEBUG", True)
            data.setdefault("TEMPLATES_AUTO_RELOAD", True)
        elif env == "Testing":
            data.setdefault("DEBUG", True)
            data.setdefault("TESTING", True)
        elif env == "Production":
            data.setdefault("SPACY_LANG_MODEL", "en_core_web_lg")
        
        super().__init__(**data)


def get_settings() -> Settings:
    """
    Factory function to get application settings.
    
    Returns:
        Settings: Configured Settings instance
    """
    return Settings()