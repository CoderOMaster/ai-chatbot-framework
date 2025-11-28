from __future__ import annotations

from typing import Iterable

from jinja2 import Undefined


def split_sentence(sentence: str | None) -> list[str]:
    """Split dialogue segments on the mandated "###" delimiter.

    The dialogue manager relies on "###" as a segment boundary, so this helper
    ensures that all callers observe that contract while gracefully handling
    None or empty strings.
    """

    if not sentence:
        return []

    return sentence.split("###")


class SilentUndefined(Undefined):
    """Jinja2 Undefined that silently returns placeholders for undefined values."""

    def _fail_with_undefined_error(self, *args, **kwargs) -> str:  # noqa: D401
        return "undefined"

    __add__ = __radd__ = __mul__ = __rmul__ = __div__ = __rdiv__ = __truediv__ = (
        __rtruediv__
    ) = __floordiv__ = __rfloordiv__ = __mod__ = __rmod__ = __pos__ = __neg__ = (
        __call__
    ) = __getitem__ = __lt__ = __le__ = __gt__ = __ge__ = __int__ = __float__ = (
        __complex__
    ) = __pow__ = __rpow__ = _fail_with_undefined_error


__all__ = ["SilentUndefined", "split_sentence"]