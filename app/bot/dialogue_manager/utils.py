from typing import Any, Dict, List

from jinja2 import Undefined


def split_sentence(sentence: str, delimiter: str = "###") -> List[str]:
    """Split a sentence into parts using the provided delimiter.

    The default delimiter is '###' but callers should provide an explicit delimiter
    when the template system requires determinism to avoid embedded magic constants.

    Args:
        sentence: The input string to split.
        delimiter: The delimiter string to split on. Defaults to '###'.

    Returns:
        A list of string segments.
    """
    return sentence.split(delimiter)


def make_context(**kwargs: Any) -> Dict[str, Any]:
    """Create and return a fresh context dictionary.

    This helper avoids using mutable default arguments (e.g. context: dict = {})
    by always returning a new dict, suitable for use as a Jinja context.
    """
    return dict(**kwargs)


class SilentUndefined(Undefined):
    """
    A jinja2 Undefined subclass that suppresses errors and returns a safe
    placeholder string for missing values.

    This makes template rendering deterministic when variables are absent by
    returning the literal string "undefined" for most operations.
    """

    def _fail_with_undefined_error(self, *args: Any, **kwargs: Any) -> str:  # type: ignore[override]
        return "undefined"

    def __str__(self) -> str:
        return "undefined"


    # Map many magic operations to the failure handler so they don't raise.
    __add__ = __radd__ = __mul__ = __rmul__ = __div__ = __rdiv__ = __truediv__ = (
        __rtruediv__
    ) = __floordiv__ = __rfloordiv__ = __mod__ = __rmod__ = __pos__ = __neg__ = (
        __call__
    ) = __getitem__ = __lt__ = __le__ = __gt__ = __ge__ = __int__ = __float__ = (
        __complex__
    ) = __pow__ = __rpow__ = _fail_with_undefined_error


__all__ = ["split_sentence", "make_context", "SilentUndefined"]