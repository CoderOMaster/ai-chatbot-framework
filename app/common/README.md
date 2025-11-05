ai_chatbot_common

This package contains shared configuration and DTOs used across services.

Importing
---------

Use:
    from app.common.config import Settings, get_settings
or:
    from app.common import Settings, get_settings

Backwards compatibility
-----------------------
Previously configuration was exposed from `app.config`. Replace imports like

    from app.config import app_config

with

    from app.common.config import get_settings
    app_config = get_settings()

Versioning
----------
Treat changes to Settings field names as potentially breaking. Use semantic
versioning for this package and update consumers accordingly.