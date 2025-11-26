"""Lightweight package initializer for intent classifiers.

This module purposefully avoids importing concrete classifier implementations at
import time to keep startup overhead low (important for microservices and
serverless functions). Use get_intent_classifier_class or create_intent_classifier
to lazily load implementations when needed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Type
import importlib

if TYPE_CHECKING:
    # Imported only for type-checking to avoid pulling implementations at runtime
    from app.bot.nlu.pipeline import NLUComponent

# Mapping of classifier keys to their import path. New implementations can be
# registered here or injected by replacing this mapping at runtime.
CLASSIFIERS: Dict[str, str] = {
    "sklearn": "app.bot.nlu.intent_classifiers.sklearn_intent_classifer.SklearnIntentClassifier",
}


def get_intent_classifier_class(name: str = "sklearn") -> Type["NLUComponent"]:
    """Lazily import and return the intent classifier class by name.

    Args:
        name: key identifying the classifier implementation in CLASSIFIERS.

    Raises:
        KeyError: if the requested classifier name is not registered.
        ImportError/AttributeError: if the module or class cannot be imported.

    Returns:
        The classifier class (subclass of NLUComponent).
    """
    path = CLASSIFIERS.get(name)
    if path is None:
        raise KeyError(f"Unknown classifier '{name}'. Available: {list(CLASSIFIERS.keys())}")

    module_name, class_name = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    return cls  # type: ignore[return-value]


def create_intent_classifier(name: str = "sklearn", *args: Any, **kwargs: Any) -> "NLUComponent":
    """Instantiate a classifier implementation lazily.

    This keeps package import time cheap and allows callers to control when
    heavyweight libraries get imported (e.g., only during training or when a
    runtime actually needs a classifier instance).
    """
    cls = get_intent_classifier_class(name)
    return cls(*args, **kwargs)  # type: ignore[return-value]


__all__ = ["get_intent_classifier_class", "create_intent_classifier", "CLASSIFIERS"]