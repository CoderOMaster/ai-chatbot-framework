"""Tests for the shared application config accessor."""

from __future__ import annotations

import importlib
import sys
from typing import Callable

import pytest

from core.settings import AppConfig


@pytest.fixture(name="reload_app_config")
def fixture_reload_app_config(monkeypatch: pytest.MonkeyPatch) -> Callable[[Callable[[], AppConfig]], object]:
    """Reload :mod:`app.config` while patching ``from_envvar`` for isolation."""

    def _reload(fake_from_envvar: Callable[[], AppConfig]) -> object:
        module_name = "app.config"
        if module_name in sys.modules:
            del sys.modules[module_name]
        monkeypatch.setattr("core.settings.from_envvar", fake_from_envvar)
        return importlib.import_module(module_name)

    return _reload


def test_app_config_exports_loader_result_once(reload_app_config: Callable[[Callable[[], AppConfig]], object]) -> None:
    """Ensure ``app.config`` exposes whatever ``from_envvar`` returned exactly once."""

    sentinel = AppConfig()
    call_count = 0

    def fake_from_envvar() -> AppConfig:
        nonlocal call_count
        call_count += 1
        return sentinel

    module = reload_app_config(fake_from_envvar)

    assert module.app_config is sentinel
    assert call_count == 1


def test_app_config_remains_appconfig_type(reload_app_config: Callable[[Callable[[], AppConfig]], object]) -> None:
    """Verify the exported ``app_config`` is an instance of ``AppConfig``."""

    sentinel = AppConfig()

    module = reload_app_config(lambda: sentinel)

    assert isinstance(module.app_config, AppConfig)
    assert module.app_config is sentinel