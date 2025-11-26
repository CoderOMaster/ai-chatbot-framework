"""Utility helpers for the dialogue manager.

This module exposes small, dependency-free utilities used across the dialogue
manager. It intentionally keeps SilentUndefined here so callers (e.g. the
dialogue manager) can configure a jinja2.Environment(..., undefined=SilentUndefined)
without templates importing application code directly.
"""
from typing import List, Optional

from jinja2 import Undefined


def split_sentence(sentence: Optional[str]) -> List[str]:
    """Split a string into segments using the exact '###' delimiter.

    Contract:
    - The literal sequence '###' is treated as the segment delimiter.
    - If `sentence` is None the function returns an empty list (safety for callers
      that may pass missing values).
    - For all other string inputs the behavior mirrors str.split("###") so that
      callers relying on that semantics remain compatible.

    Args:
        sentence: The input string to split or None.

    Returns:
        A list of string segments. If `sentence` is None this will be an empty list.
    """
    if sentence is None:
        return []
    return sentence.split("###")


class SilentUndefined(Undefined):
    """A jinja2 Undefined that suppresses errors and returns a safe placeholder.

    Use this with jinja2.Environment(undefined=SilentUndefined) so template
    evaluation never raises for missing values and instead yields the string
    "undefined" for most operations. This class intentionally avoids
    importing application logic into templates.
    """

    def _fail_with_undefined_error(self, *args, **kwargs) -> str:
        return "undefined"


# Re-export public symbols
__all__ = ["split_sentence", "SilentUndefined"]