import os
from ai_chatbot_common.config import Settings, get_settings


def test_settings_defaults():
    s = Settings()
    assert s.MONGODB_HOST.startswith("mongodb://")
    assert s.MONGODB_DATABASE
    assert isinstance(s.DEBUG, bool)


def test_get_settings_cached():
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MONGODB_DATABASE", "test-db")
    s = Settings()
    assert s.MONGODB_DATABASE == "test-db"