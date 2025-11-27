import importlib
import sys
import pytest
from typing import Any


def _reload_app_config() -> Any:
    """Helper to (re)import the app.config module fresh.

    Removes app.config from sys.modules if present, then imports it so module-level
    initialization (including calling load_config) runs.
    """
    if "app.config" in sys.modules:
        del sys.modules["app.config"]
    return importlib.import_module("app.config")


def test_settings_initialized_with_mocked_config(monkeypatch) -> None:
    """Verify that app.config.settings is assigned to the object returned by
    app.config_loader.load_config() at import time and that it is an instance of
    BaseConfig.
    """
    # Import the loader to access BaseConfig and to patch load_config
    import app.config_loader as loader

    class DummyConfig(loader.BaseConfig):
        pass

    dummy = DummyConfig()

    # Patch load_config to return our dummy instance
    monkeypatch.setattr(loader, "load_config", lambda: dummy)

    # Reload app.config so the patched load_config is used during module import
    config = _reload_app_config()

    assert config.settings is dummy
    assert isinstance(config.settings, loader.BaseConfig)
    # Ensure exports include the expected names
    assert "settings" in getattr(config, "__all__", [])
    assert "BaseConfig" in getattr(config, "__all__", [])


def test_load_config_called_once_on_import(monkeypatch) -> None:
    """Ensure load_config() is invoked exactly once when importing app.config.
    """
    import app.config_loader as loader

    call_count = {"n": 0}

    def spy_load_config():
        call_count["n"] += 1
        # return a minimal BaseConfig instance
        return loader.BaseConfig()

    monkeypatch.setattr(loader, "load_config", spy_load_config)

    _reload_app_config()

    assert call_count["n"] == 1


def test_import_raises_when_loader_fails(monkeypatch) -> None:
    """If the loader raises an exception (e.g., missing env vars), importing
    app.config should propagate that error.
    """
    import app.config_loader as loader

    def raise_error():
        raise RuntimeError("configuration loading failed")

    monkeypatch.setattr(loader, "load_config", raise_error)

    # Ensure fresh import triggers the error
    if "app.config" in sys.modules:
        del sys.modules["app.config"]

    with pytest.raises(RuntimeError, match="configuration loading failed"):
        importlib.import_module("app.config")