"""Application configuration module."""
from app.config_loader import BaseConfig, load_config

# Load configuration from environment
settings: BaseConfig = load_config()

__all__ = ["settings", "BaseConfig"]