"""Package entry point for optional LLM-based NLU components."""

from .zero_shot_nlu_openai import ZeroShotNLUOpenAI

__all__ = ["ZeroShotNLUOpenAI"]

# Hide the submodule from the public API
del zero_shot_nlu_openai