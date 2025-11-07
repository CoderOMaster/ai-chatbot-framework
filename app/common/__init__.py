"""Common shared utilities for AI Chatbot Framework.

Exposes Settings and get_settings for configuration management.
Prefer importing from ai_chatbot_common to decouple from app layout.

Example:
    from ai_chatbot_common.config import Settings, get_settings
    settings = get_settings()
"""

from .config import Settings, get_settings

__all__ = ["Settings", "get_settings"]