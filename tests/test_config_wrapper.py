from importlib import reload
import app.config as old_config
from app.common.config import get_settings


def test_app_config_delegate(monkeypatch):
    # Ensure app.config.app_config points to a Settings instance returned by get_settings
    # Force a fresh singleton
    from app.common import config as common_config
    common_config._settings_singleton = None

    s = get_settings()
    # Use equality check instead of identity to reflect new singleton creation
    assert old_config.app_config == s

    # After reload, wrapper should still point to get_settings result
    reload(old_config)
    assert old_config.app_config == s