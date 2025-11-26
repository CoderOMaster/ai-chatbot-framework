"""LLM NLU package initializer.

This module re-exports ZeroShotNLUOpenAI in a side-effect free way: the
actual submodule is imported lazily when the symbol is accessed. This
prevents network calls, template loading or other heavy operations from
running at import time in test suites or services that merely check for
availability of the package.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import importlib

__all__ = ["ZeroShotNLUOpenAI"]

if TYPE_CHECKING:  # pragma: no cover - for type checkers only
    from .zero_shot_nlu_openai import ZeroShotNLUOpenAI


def __getattr__(name: str) -> Any:
    """Lazily import attributes from submodules to avoid side effects at import time.

    Only supports re-exporting defined names in __all__.
    """
    if name in __all__:
        module = importlib.import_module(".zero_shot_nlu_openai", __package__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Return a friendly dir() listing including re-exported symbols."""
    return sorted(list(globals().keys()) + __all__)