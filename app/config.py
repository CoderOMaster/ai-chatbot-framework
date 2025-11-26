"""
Application configuration module providing backward compatibility.

This module maintains compatibility with existing imports while delegating
to the new Pydantic-based configuration in app.common.config.

Note: This module imports from project_config (root-level) to avoid
name collision with the app.config module itself.
"""

from app.common.config import Settings, get_settings
from project_config import from_envvar

# Create singleton instance for backward compatibility
app_config = get_settings()

__all__ = ["app_config", "Settings", "get_settings", "from_envvar"]