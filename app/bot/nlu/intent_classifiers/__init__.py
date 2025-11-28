"""Lazy loader for intent classifier interfaces."""
from importlib import import_module
from typing import Any, Dict, List

_CLASSIFIERS: Dict[str, str] = {
    "SklearnIntentClassifier": (
        "app.bot.nlu.intent_classifiers.sklearn_intent_classifer"
    )
}

__all__: List[str] = list(_CLASSIFIERS.keys())


def __getattr__(name: str) -> Any:  # pragma: no cover - module-level helper
    """Lazily import the requested classifier interface."""
    module_path = _CLASSIFIERS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__} has no attribute {name}")

    module = import_module(module_path)
    return getattr(module, name)


def __dir__() -> List[str]:  # pragma: no cover - module-level helper
    """Expose available classifier interfaces for tooling."""
    return sorted(__all__ + list(globals().keys()))