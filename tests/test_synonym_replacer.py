import pytest

from app.bot.nlu.entity_extractors.synonym_replacer import SynonymReplacer


@pytest.fixture

def synonyms_map() -> dict[str, str]:
    return {"Hello": "hi", "WORLD": "earth", "123": "numbers"}


@pytest.fixture

def replacer(synonyms_map: dict[str, str]) -> SynonymReplacer:
    return SynonymReplacer(synonyms=synonyms_map)


def test_init_normalizes_keys(synonyms_map: dict[str, str]) -> None:
    """Ensure the SynonymReplacer lowercases provided synonym keys."""
    replacer = SynonymReplacer(synonyms=synonyms_map)
    assert "hello" in replacer.synonyms
    assert "world" in replacer.synonyms
    assert "123" in replacer.synonyms


def test_replace_synonyms_replaces_matching_values(replacer: SynonymReplacer) -> None:
    """Confirm matching entity values are replaced with their root synonyms."""
    entities = {"greeting": "Hello", "planet": "world"}
    result = replacer.replace_synonyms(entities)

    assert result["greeting"] == "hi"
    assert result["planet"] == "earth"


def test_replace_synonyms_handles_non_string_values(replacer: SynonymReplacer) -> None:
    """Verify non-string entity values are stringified before lookup."""
    entities = {"count": 123}
    result = replacer.replace_synonyms(entities)

    assert result["count"] == "numbers"


def test_replace_synonyms_leaves_unknown_values(replacer: SynonymReplacer) -> None:
    """Ensure values without synonyms remain unchanged."""
    entities = {"color": "blue"}
    result = replacer.replace_synonyms(entities)

    assert result["color"] == "blue"


def test_process_returns_message_without_entities(replacer: SynonymReplacer) -> None:
    """Check that process returns the original message when no entities exist."""
    message = {"text": "hello"}
    processed = replacer.process(message.copy())

    assert processed == {"text": "hello"}


def test_process_replaces_entities_in_message(replacer: SynonymReplacer) -> None:
    """Ensure that message entities are replaced via process call."""
    message = {"text": "hi", "entities": {"planet": "WORLD"}}
    processed = replacer.process(message)

    assert processed["entities"]["planet"] == "earth"


def test_train_no_op(replacer: SynonymReplacer) -> None:
    """Verify train returns None as it is a no-op for synonym replacement."""
    assert replacer.train({}, "./model") is None


def test_load_returns_true(replacer: SynonymReplacer) -> None:
    """Assert load always returns True since there is nothing to load."""
    assert replacer.load("./model")