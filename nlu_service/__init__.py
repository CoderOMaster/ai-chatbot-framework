# nlu_service package: runtime inference API and trainer entrypoints

__all__ = [
    "load_models",
    "predict",
]

from .runtime import load_models, predict  # re-export