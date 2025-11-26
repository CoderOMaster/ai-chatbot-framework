"""Thin re-export layer for NLU entity extractors.

This module exposes CRFEntityExtractor and SynonymReplacer as top-level
attributes while avoiding importing their modules at import-time. Accessing
these attributes triggers a lazy import which prevents side effects (such as
heavy native library loads) when this package is imported by the pipeline
factory.
"""
from typing import TYPE_CHECKING, Any
import importlib

if TYPE_CHECKING:
    # These imports are only for type checking and IDEs; they won't execute at runtime
    from .crf_entity_extractor import CRFEntityExtractor  # type: ignore
    from .synonym_replacer import SynonymReplacer  # type: ignore

__all__ = ["CRFEntityExtractor", "SynonymReplacer"]


def __getattr__(name: str) -> Any:
    """Lazily import and return requested attribute.

    This avoids importing modules with potential side effects at package
    import time. Only the names listed in __all__ are supported.
    """
    if name == "CRFEntityExtractor":
        mod = importlib.import_module(".crf_entity_extractor", __name__)
        return getattr(mod, "CRFEntityExtractor")
    if name == "SynonymReplacer":
        mod = importlib.import_module(".synonym_replacer", __name__)
        return getattr(mod, "SynonymReplacer")
    raise AttributeError(f"module {__name__} has no attribute {name}")


def __dir__() -> list:
    """Return a directory listing including lazily exported names."""
    return sorted(list(globals().keys()) + __all__)