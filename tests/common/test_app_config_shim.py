from app.config import app_config
from ai_chatbot_common.config import get_settings


def test_app_config_shim_is_get_settings_instance():
    s = get_settings()
    assert app_config is s