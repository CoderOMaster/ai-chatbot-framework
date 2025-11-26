"""
Dialogue manager utilities for response templating and sentence processing.

This module provides pure utility functions and classes for handling Jinja2
templating operations and sentence splitting. All templating should route
through this module to maintain centralized control over template rendering.
"""

from typing import List

from jinja2 import Undefined


def split_sentence(sentence: str) -> List[str]:
    """
    Split a sentence by the delimiter '###'.

    Args:
        sentence: The input sentence to split.

    Returns:
        A list of sentence fragments split by '###'.
    """
    return sentence.split("###")


class SilentUndefined(Undefined):
    """
    Jinja2 Undefined subclass that suppresses errors and warnings.

    This class overrides all operator and magic methods to return 'undefined'
    instead of raising exceptions when undefined variables are encountered
    during template rendering. This allows templates to gracefully handle
    missing variables without failing.
    """

    def _fail_with_undefined_error(self, *args, **kwargs) -> str:
        """Return 'undefined' string instead of raising an error."""
        return "undefined"

    __add__ = __radd__ = __mul__ = __rmul__ = __div__ = __rdiv__ = __truediv__ = (
        __rtruediv__
    ) = __floordiv__ = __rfloordiv__ = __mod__ = __rmod__ = __pos__ = __neg__ = (
        __call__
    ) = __getitem__ = __lt__ = __le__ = __gt__ = __ge__ = __int__ = __float__ = (
        __complex__
    ) = __pow__ = __rpow__ = _fail_with_undefined_error