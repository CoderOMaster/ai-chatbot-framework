"""Pydantic-backed application configuration for shared services."""

from __future__ import annotations

import os
from typing import Dict, Final, Literal, MutableMapping

from pydantic import BaseSettings, Field, root_validator

EnvironmentChoice = Literal["Development", "Testing", "Production"]

DEFAULT_ENVIRONMENT: Final[EnvironmentChoice] = "Development"
ENVIRONMENT_OVERRIDES: Final[Dict[EnvironmentChoice, Dict[str, object]]] = {
    "Development": {
        "DEBUG": True,
        "Development": True,
        "TEMPLATES_AUTO_RELOAD": True,
    },
    "Testing": {
        "DEBUG": True,
        "TESTING": True,
    },
    "Production": {
        "SPACY_LANG_MODEL": "en_core_web_lg",
    },
}
ENVIRONMENT_CHOICES: Final[tuple[EnvironmentChoice, ...]] = tuple(ENVIRONMENT_OVERRIDES)


class AppConfig(BaseSettings):
    """Typed, immutable configuration loaded from environment variables."""

    APPLICATION_ENV: EnvironmentChoice = Field(
        DEFAULT_ENVIRONMENT,
        env="APPLICATION_ENV",
    )
    DEBUG: bool = False
    Development: bool = False
    TEMPLATES_AUTO_RELOAD: bool = False
    TESTING: bool = False
    MONGODB_HOST: str = Field("mongodb://127.0.0.1:27017", env="MONGODB_HOST")
    MONGODB_DATABASE: str = Field("ai-chatbot-framework", env="MONGODB_DATABASE")
    MODELS_DIR: str = Field("model_files/", env="MODELS_DIR")
    DEFAULT_FALLBACK_INTENT_NAME: str = Field("fallback", env="DEFAULT_FALLBACK_INTENT_NAME")
    DEFAULT_WELCOME_INTENT_NAME: str = Field("init_conversation", env="DEFAULT_WELCOME_INTENT_NAME")
    SPACY_LANG_MODEL: str = Field("en_core_web_md", env="SPACY_LANG_MODEL")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        allow_mutation = False
        frozen = True

    @root_validator(pre=True)
    def _apply_environment_overrides(
        cls,
        values: MutableMapping[str, object],
    ) -> MutableMapping[str, object]:
        """Ensure environment-specific defaults mirror the previous config variants."""
        env_choice = values.get("APPLICATION_ENV")
        if env_choice is None:
            env_choice = os.environ.get("APPLICATION_ENV", DEFAULT_ENVIRONMENT)
        if env_choice not in ENVIRONMENT_CHOICES:
            raise ValueError(
                "APPLICATION_ENV=%s is not valid, must be one of %s"
                % (env_choice, set(ENVIRONMENT_CHOICES))
            )
        values["APPLICATION_ENV"] = env_choice
        overrides = ENVIRONMENT_OVERRIDES[env_choice]
        for key, override_value in overrides.items():
            values.setdefault(key, override_value)
        return values


def from_envvar() -> AppConfig:
    """Create an immutable settings instance from the current environment."""
    return AppConfig()