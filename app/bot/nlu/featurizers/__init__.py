"""Lightweight package initializer for featurizers.

This module re-exports SpacyFeaturizer at the package level without importing
or initializing heavy dependencies at import time. The actual class is
imported lazily when accessed to keep service startup cheap.
"""
from importlib import import_module
from typing import TYPE_CHECKING, Any, List

__all__ = ["SpacyFeaturizer"]

if TYPE_CHECKING:  # pragma: no cover - only for type checkers
    from app.bot.nlu.featurizers.spacy_featurizer import SpacyFeaturizer


def __getattr__(name: str) -> Any:
    """Lazily import and return attributes to avoid heavy import-time work.

    Only SpacyFeaturizer is supported at the package level. Other attributes
    will raise AttributeError to mirror normal import behavior.
    """
    if name == "SpacyFeaturizer":
        module = import_module("app.bot.nlu.featurizers.spacy_featurizer")
        return getattr(module, "SpacyFeaturizer")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> List[str]:
    """Return a stable list of public attributes for tooling and introspection."""
    return sorted(__all__)