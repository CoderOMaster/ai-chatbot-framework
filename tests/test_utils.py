import pytest

from jinja2 import Environment

from app.bot.dialogue_manager import utils


@pytest.fixture
def jinja_env() -> Environment:
    """Provide a Jinja environment configured with the SilentUndefined class."""

    return Environment(undefined=utils.SilentUndefined)


def test_split_sentence_none_input_returns_empty_list() -> None:
    """split_sentence should return an empty list when given None."""

    assert utils.split_sentence(None) == []


def test_split_sentence_empty_string_returns_empty_list() -> None:
    """split_sentence should return an empty list for empty string inputs."""

    assert utils.split_sentence("") == []


def test_split_sentence_splits_on_delimiter() -> None:
    """split_sentence should split input on the ### delimiter without trimming segments."""

    source = "Hello world###This is a test###Another segment"
    assert utils.split_sentence(source) == [
        "Hello world",
        "This is a test",
        "Another segment",
    ]


def test_split_sentence_handles_consecutive_delimiters() -> None:
    """split_sentence should treat consecutive delimiters as empty segments."""

    assert utils.split_sentence("###") == ["", ""]


def test_split_sentence_no_delimiter_returns_original_string() -> None:
    """If no delimiter is present, split_sentence should leave the string intact."""

    value = "Single segment with no delimiter"
    assert utils.split_sentence(value) == [value]


def test_silent_undefined_basic_operations_return_placeholder() -> None:
    """SilentUndefined should silently return the placeholder string for common operations."""

    undefined = utils.SilentUndefined()

    assert (undefined + 5) == "undefined"
    assert (undefined * 2) == "undefined"
    assert undefined["missing"] == "undefined"
    assert (undefined < 10) == "undefined"
    assert str(undefined) == "undefined"


def test_silent_undefined_in_template_returns_placeholder(jinja_env: Environment) -> None:
    """Templates rendered with SilentUndefined should show the placeholder for missing values."""

    template = jinja_env.from_string("Value: {{ missing }}")
    assert template.render() == "Value: undefined"


def test_module_exports_expected_members() -> None:
    """The module should explicitly export the helper names declared in __all__."""

    assert set(utils.__all__) == {"SilentUndefined", "split_sentence"}