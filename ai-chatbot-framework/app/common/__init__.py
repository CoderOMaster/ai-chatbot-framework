"""Common shared utilities for AI Chatbot services.

Exports:
- Settings: Pydantic BaseSettings for environment-driven configuration
- get_settings: factory for Settings singleton per process
- lifecycle helpers for DI patterns (placeholders for future)
"""
from .config import Settings, get_settings

__all__ = ["Settings", "get_settings"]