"""Utility functions for dialogue processing and string manipulation."""

from typing import List
from jinja2 import Undefined


def split_sentence(sentence: str, separator: str = "###") -> List[str]:
    """
    Split a sentence by a configurable separator.
    
    Args:
        sentence: The sentence to split.
        separator: The delimiter to split on. Defaults to "###".
    
    Returns:
        A list of sentence fragments.
    """
    return sentence.split(separator)


def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace in text by removing extra spaces and newlines.
    
    Args:
        text: The text to normalize.
    
    Returns:
        Text with normalized whitespace.
    """
    return " ".join(text.split())


def strip_punctuation(text: str) -> str:
    """
    Remove leading and trailing punctuation from text.
    
    Args:
        text: The text to clean.
    
    Returns:
        Text with punctuation stripped.
    """
    return text.strip('.,!?;:\'"')


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    Truncate text to a maximum length with optional suffix.
    
    Args:
        text: The text to truncate.
        max_length: Maximum length of the result. Defaults to 100.
        suffix: Suffix to append if truncated. Defaults to "...".
    
    Returns:
        Truncated text with suffix if needed.
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


class SilentUndefined(Undefined):
    """
    Jinja2 Undefined subclass that suppresses errors and warnings.
    
    Returns "undefined" string instead of raising exceptions for undefined variables.
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