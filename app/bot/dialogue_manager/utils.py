from typing import List

from jinja2 import Undefined


class SilentUndefined(Undefined):
    """
    Jinja2 Undefined subclass that suppresses errors and warnings.
    
    Returns "undefined" string for all operations instead of raising exceptions,
    enabling graceful handling of missing template variables.
    """

    def _fail_with_undefined_error(self, *args, **kwargs) -> str:
        return "undefined"

    __add__ = __radd__ = __mul__ = __rmul__ = __div__ = __rdiv__ = __truediv__ = (
        __rtruediv__
    ) = __floordiv__ = __rfloordiv__ = __mod__ = __rmod__ = __pos__ = __neg__ = (
        __call__
    ) = __getitem__ = __lt__ = __le__ = __gt__ = __ge__ = __int__ = __float__ = (
        __complex__
    ) = __pow__ = __rpow__ = _fail_with_undefined_error


def split_sentence(sentence: str) -> List[str]:
    """
    Split a sentence by the delimiter '###'.
    
    Args:
        sentence: The input string to split.
        
    Returns:
        List of sentence fragments split by '###' delimiter.
        
    Raises:
        TypeError: If sentence is not a string.
    """
    if not isinstance(sentence, str):
        raise TypeError(f"Expected str, got {type(sentence).__name__}")
    return sentence.split("###")