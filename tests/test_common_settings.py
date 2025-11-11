import os
import importlib
import types
import builtins
from pathlib import Path

import pytest

from app.common.config import Settings


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    # Ensure these env vars don't leak between tests
    for key in [
        "MONGODB_HOST",
        "MONGODB_DATABASE",
        "JWT_SECRET",
        "MODELS_DIR",
        "LLM_API_KEY",
        "jwt_secret",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_settings_defaults():
    s = Settings()
    assert s.MONGODB_HOST == "mongodb://localhost:27017"
    assert s.MONGODB_DATABASE == "chatbot"
    assert s.JWT_SECRET == "dev-secret"
    assert s.MODELS_DIR == "models"
    assert s.LLM_API_KEY is None


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("MONGODB_DATABASE", "prod-db")
    s = Settings()
    assert s.MONGODB_DATABASE == "prod-db"


def test_case_insensitive_env(monkeypatch):
    # case_sensitive = False -> lower-case env var should be read
    monkeypatch.setenv("jwt_secret", "lowercase-secret")
    s = Settings()
    assert s.JWT_SECRET == "lowercase-secret"


def test_repr_redacts_sensitive_values(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "super-secret")
    monkeypatch.setenv("LLM_API_KEY", "api-key-value")
    s = Settings()
    r = repr(s)
    assert "***redacted***" in r
    assert "super-secret" not in r
    assert "api-key-value" not in r


def test_env_file_loading(tmp_path: Path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("MONGODB_DATABASE=from-env-file\n")

    # Ensure no overriding env var is set in the real environment
    monkeypatch.delenv("MONGODB_DATABASE", raising=False)

    s = Settings(_env_file=str(env_path))
    assert s.MONGODB_DATABASE == "from-env-file"


def test_common_init_exports_settings():
    # Import from app.common should resolve to same Settings class
    from app.common import Settings as Exported
    from app.common.config import Settings as Actual

    assert Exported is Actual

    # __all__ should contain Settings for star imports
    import app.common as common_pkg
    assert "Settings" in getattr(common_pkg, "__all__", [])