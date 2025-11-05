"""ai_chatbot_common package

Expose commonly used helpers such as Settings to make imports simple.
"""
from .config import Settings, get_settings

__all__ = ["Settings", "get_settings"]