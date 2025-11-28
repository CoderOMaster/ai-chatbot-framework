"""Expose the immutable application settings for the shared services."""

from typing import Final

from core.settings import AppConfig, from_envvar

app_config: Final[AppConfig] = from_envvar()