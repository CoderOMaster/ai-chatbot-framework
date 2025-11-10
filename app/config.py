# Deprecated shim: preserve old import path while migrating to common Settings
from ai_chatbot_common.config import get_settings as _get_settings

# Maintain previous name used across codebase
app_config = _get_settings()