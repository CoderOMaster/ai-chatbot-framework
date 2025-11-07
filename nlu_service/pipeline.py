# Compatibility module for code importing nlu_service.pipeline
# Re-export predict/load_models from runtime, and FastAPI app if needed
from .runtime import predict, load_models, app  # noqa: F401

__all__ = ["predict", "load_models", "app"]