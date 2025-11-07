# Backwards-compatibility shim. Prefer using ai_chatbot_common.config
from ai_chatbot_common.config import get_settings

# Legacy name expected by existing modules
app_config = get_settings()