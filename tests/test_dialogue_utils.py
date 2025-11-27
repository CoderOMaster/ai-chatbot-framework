import pytest
from app.bot.dialogue_manager import utils
from app.bot.dialogue_manager.utils import (
    split_sentence,
    normalize_whitespace,
    strip_punctuation,
    truncate_text,
    SilentUndefined,
)


@pytest.fixture
def sample_text() -> str:
    """Provide a sample multi-line text with irregular whitespace."""
    return "  This   is\na\t\t test  "


def test_split_sentence_default_separator() -> None:
    """split_sentence should split using the default separator '###'."""
    s = "hello###world###again"
    assert split_sentence(s) == ["hello", "world", "again"]


def test_split_sentence_custom_separator() -> None:
    """split_sentence should split using a custom separator when provided."""
    s = "a|b|c"
    assert split_sentence(s, separator="|") == ["a", "b", "c"]


def test_split_sentence_no_separator_present() -> None:
    """If the separator is not present the original string should be returned as a single element list."""
    s = "hello world"
    assert split_sentence(s) == ["hello world"]


def test_split_sentence_empty_string() -> None:
    """Splitting an empty string should return a list containing an empty string."""
    assert split_sentence("") == [""]


def test_split_sentence_non_string_raises() -> None:
    """Passing a non-string (e.g. None) should raise an AttributeError because .split won't exist."""
    with pytest.raises(AttributeError):
        # type: ignore[arg-type]
        split_sentence(None)  # type: ignore


def test_normalize_whitespace_collapses_and_trims(sample_text: str) -> None:
    """normalize_whitespace should collapse consecutive whitespace and trim edges."""
    normalized = normalize_whitespace(sample_text)
    assert normalized == "This is a test"


def test_normalize_whitespace_empty_string() -> None:
    """normalize_whitespace should return an empty string when given an empty string."""
    assert normalize_whitespace("") == ""


def test_normalize_whitespace_non_string_raises() -> None:
    """Passing non-string should raise AttributeError (no split method)."""
    with pytest.raises(AttributeError):
        # type: ignore[arg-type]
        normalize_whitespace(None)  # type: ignore


def test_strip_punctuation_leading_and_trailing() -> None:
    """Leading and trailing punctuation characters should be stripped."""
    assert strip_punctuation("?!Hello!!!") == "Hello"


def test_strip_punctuation_internal_punctuation_preserved() -> None:
    """Punctuation inside the text should be preserved; only leading/trailing are removed."""
    assert strip_punctuation("don't!") == "don't"


def test_strip_punctuation_only_punctuation_returns_empty() -> None:
    """A string made only of punctuation characters should become an empty string."""
    assert strip_punctuation("!!!???,,,,,") == ""


def test_strip_punctuation_empty() -> None:
    """An empty string remains empty after stripping punctuation."""
    assert strip_punctuation("") == ""


def test_truncate_text_no_truncate() -> None:
    """When text length is less than max_length, the original text is returned."""
    short = "short text"
    assert truncate_text(short, max_length=50) == short


def test_truncate_text_exact_length() -> None:
    """When text length equals max_length, the original text is returned."""
    s = "12345"
    assert truncate_text(s, max_length=5) == s


def test_truncate_text_truncates_with_default_suffix() -> None:
    """Long text should be truncated and end with the default suffix '...'."""
    text = "a" * 20
    result = truncate_text(text, max_length=10)
    assert result == ("a" * (10 - len("..."))) + "..."
    assert result.endswith("...")


def test_truncate_text_with_custom_suffix() -> None:
    """Custom suffix should be appended when truncation occurs."""
    text = "abcdefghij"
    result = truncate_text(text, max_length=6, suffix="(more)")
    assert result == text[: 6 - len("(more)")] + "(more)"


def test_truncate_text_max_length_equals_suffix_length() -> None:
    """If max_length equals suffix length the result should be exactly the suffix."""
    text = "HelloWorld"
    suffix = "..."
    assert truncate_text(text, max_length=len(suffix), suffix=suffix) == suffix


def test_truncate_text_max_length_smaller_than_suffix() -> None:
    """If max_length is smaller than the suffix length the implementation will slice with a negative index; ensure deterministic behaviour."""
    text = "HelloWorld"
    # max_length smaller than suffix length -> slice index negative
    result = truncate_text(text, max_length=2, suffix="...")
    # expected behavior: text[:2-3] -> text[:-1] + suffix
    assert result == text[:-1] + "..."


@pytest.fixture
def silent() -> SilentUndefined:
    """Provide a SilentUndefined instance for testing jinja undefined-safe behaviour."""
    return SilentUndefined()


def test_silent_undefined_addition_returns_string(silent: SilentUndefined) -> None:
    """Arithmetic operations on SilentUndefined should return the string 'undefined'."""
    assert silent + 5 == "undefined"
    assert 5 + silent == "undefined"


def test_silent_undefined_multiplication_and_call(silent: SilentUndefined) -> None:
    """Other magic operations like multiplication and calling should return 'undefined'."""
    assert silent * 3 == "undefined"
    assert silent() == "undefined"


def test_silent_undefined_getitem_and_comparison(silent: SilentUndefined) -> None:
    """Indexing and comparison operations should return 'undefined' without raising exceptions."""
    assert silent["key"] == "undefined"
    assert (silent < 10) == "undefined"


def test_silent_undefined_direct_magic_calls_return_string(silent: SilentUndefined) -> None:
    """Directly calling the magic methods (e.g. __int__) should return the string 'undefined'. Note: using built-ins like int() can still raise TypeError because Python expects an int result."""
    assert silent._fail_with_undefined_error() == "undefined"
    assert silent.__int__() == "undefined"
    assert silent.__float__() == "undefined"


def test_silent_undefined_builtin_int_raises_typeerror(silent: SilentUndefined) -> None:
    """Calling int(...) on SilentUndefined will raise a TypeError because __int__ returns a non-int value."""
    with pytest.raises(TypeError):
        int(silent)


def test_module_level_imports_and_helpers_exist() -> None:
    """Sanity check that the module exposes the expected helpers and classes."""
    assert hasattr(utils, "split_sentence")
    assert hasattr(utils, "normalize_whitespace")
    assert hasattr(utils, "strip_punctuation")
    assert hasattr(utils, "truncate_text")
    assert hasattr(utils, "SilentUndefined")