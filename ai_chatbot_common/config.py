# Thin proxy to keep a stable import path
from app.common.config import Settings, get_settings  # noqa: F401

__all__ = ["Settings", "get_settings"]