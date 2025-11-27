"""Unit tests for dialogue_manager.utils module."""

import pytest
from app.bot.dialogue_manager.utils import (
    split_sentence,
    normalize_whitespace,
    strip_punctuation,
    truncate_text,
    SilentUndefined,
)


class TestSplitSentence:
    """Tests for split_sentence function."""

    def test_split_with_default_separator(self):
        """Test splitting with default ### separator."""
        result = split_sentence("hello###world###test")
        assert result == ["hello", "world", "test"]

    def test_split_with_custom_separator(self):
        """Test splitting with custom separator."""
        result = split_sentence("hello|world|test", separator="|")
        assert result == ["hello", "world", "test"]

    def test_split_no_separator_found(self):
        """Test splitting when separator is not found."""
        result = split_sentence("hello world")
        assert result == ["hello world"]

    def test_split_empty_string(self):
        """Test splitting empty string."""
        result = split_sentence("")
        assert result == [""]


class TestNormalizeWhitespace:
    """Tests for normalize_whitespace function."""

    def test_normalize_multiple_spaces(self):
        """Test normalizing multiple spaces."""
        result = normalize_whitespace("hello    world")
        assert result == "hello world"

    def test_normalize_newlines_and_tabs(self):
        """Test normalizing newlines and tabs."""
        result = normalize_whitespace("hello\n\tworld")
        assert result == "hello world"

    def test_normalize_leading_trailing_spaces(self):
        """Test normalizing leading and trailing spaces."""
        result = normalize_whitespace("   hello world   ")
        assert result == "hello world"

    def test_normalize_already_normalized(self):
        """Test normalizing already normalized text."""
        result = normalize_whitespace("hello world")
        assert result == "hello world"


class TestStripPunctuation:
    """Tests for strip_punctuation function."""

    def test_strip_trailing_period(self):
        """Test stripping trailing period."""
        result = strip_punctuation("hello.")
        assert result == "hello"

    def test_strip_multiple_punctuation(self):
        """Test stripping multiple punctuation marks."""
        result = strip_punctuation("...hello!!!")
        assert result == "hello"

    def test_strip_quotes(self):
        """Test stripping quotes."""
        result = strip_punctuation('"hello"')
        assert result == "hello"

    def test_strip_no_punctuation(self):
        """Test text without punctuation."""
        result = strip_punctuation("hello")
        assert result == "hello"

    def test_strip_internal_punctuation_preserved(self):
        """Test that internal punctuation is preserved."""
        result = strip_punctuation("don't.")
        assert result == "don't"


class TestTruncateText:
    """Tests for truncate_text function."""

    def test_truncate_long_text(self):
        """Test truncating text longer than max_length."""
        result = truncate_text("hello world this is a long text", max_length=10)
        assert result == "hello w..."
        assert len(result) == 10

    def test_truncate_short_text(self):
        """Test text shorter than max_length."""
        result = truncate_text("hello", max_length=100)
        assert result == "hello"

    def test_truncate_custom_suffix(self):
        """Test truncating with custom suffix."""
        result = truncate_text("hello world", max_length=8, suffix=">>")
        assert result == "hello>>"

    def test_truncate_exact_length(self):
        """Test text exactly at max_length."""
        result = truncate_text("hello", max_length=5)
        assert result == "hello"

    def test_truncate_empty_string(self):
        """Test truncating empty string."""
        result = truncate_text("", max_length=10)
        assert result == ""


class TestSilentUndefined:
    """Tests for SilentUndefined class."""

    def test_undefined_returns_string(self):
        """Test that undefined operations return 'undefined' string."""
        undefined = SilentUndefined()
        assert undefined + "test" == "undefined"
        assert "test" + undefined == "undefined"

    def test_undefined_arithmetic(self):
        """Test arithmetic operations on undefined."""
        undefined = SilentUndefined()
        assert undefined * 5 == "undefined"
        assert undefined / 2 == "undefined"
        assert undefined - 1 == "undefined"

    def test_undefined_comparison(self):
        """Test comparison operations on undefined."""
        undefined = SilentUndefined()
        assert (undefined < 5) == "undefined"
        assert (undefined > 5) == "undefined"
        assert (undefined == 5) == "undefined"

    def test_undefined_indexing(self):
        """Test indexing operations on undefined."""
        undefined = SilentUndefined()
        assert undefined[0] == "undefined"
        assert undefined["key"] == "undefined"

    def test_undefined_call(self):
        """Test calling undefined as function."""
        undefined = SilentUndefined()
        assert undefined() == "undefined"