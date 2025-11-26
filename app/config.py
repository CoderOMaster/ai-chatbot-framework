"""Application config accessor.

This module provides a lazy, import-safe accessor for application settings.
It prefers loading configuration from "core.settings.from_envvar" (the new
centralized provider). If that module isn't available yet, it falls back to
legacy "config.from_envvar" for backwards compatibility.

Access the settings via get_app_config() or the module-level `app_config`
proxy (keeps older import patterns working without evaluating env at import
time).
"""
from typing import Any, Optional


# Prefer the new centralized settings provider; fall back to the legacy one.
try:
    from core.settings import from_envvar  # type: ignore
except Exception:  # pragma: no cover - fallback for environments not yet migrated
    from config import from_envvar  # type: ignore


_real_config: Optional[Any] = None


def _load_config() -> Any:
    """Load and cache the application settings instance.

    This defers environment access until the first time settings are needed,
    avoiding side-effects at module import time.
    """
    global _real_config
    if _real_config is None:
        _real_config = from_envvar()
    return _real_config


class _AppConfigProxy:
    """Proxy object that lazily resolves the real settings instance.

    It implements attribute access and common dunder methods so existing
    code that imports `app_config` continues to work without triggering
    environment reads at import time.
    """

    def __getattr__(self, item: str) -> Any:
        return getattr(_load_config(), item)

    def __repr__(self) -> str:  # pragma: no cover - simple delegation
        return repr(_load_config())

    def __bool__(self) -> bool:  # pragma: no cover - delegate truthiness
        return bool(_load_config())


#: Backwards-compatible module-level accessor. Use get_app_config() instead
#: when possible to make dependencies explicit.
app_config: _AppConfigProxy = _AppConfigProxy()


def get_app_config() -> Any:
    """Return the application settings instance (loaded lazily).

    Prefer calling this function in constructors or dependency injection code
    to make configuration access explicit and test-friendly.
    """
    return _load_config()