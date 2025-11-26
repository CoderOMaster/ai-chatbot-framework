"""
Root configuration module providing backward compatibility.

This module maintains compatibility with existing imports while delegating
to the new Pydantic-based configuration in app.common.config.
"""

import os
import dotenv
from app.common.config import Settings, get_settings

dotenv.load_dotenv()


def from_envvar():
    """
    Get configuration instance from environment variables.
    
    This function provides backward compatibility with the old configuration API.
    Reads only environment-based settings, not runtime state.
    
    Returns:
        Settings: Configured Settings instance
    """
    return get_settings()