"""Backward-compatible wrapper for the new shared Settings.

Old consumers used:
    from app.config import app_config

Keep that API but delegate to app.common.config.get_settings().
"""
from app.common.config import get_settings

# Backwards compatible name used throughout the codebase
app_config = get_settings()