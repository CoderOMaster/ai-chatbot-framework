import sys
import types
from unittest.mock import Mock
from typing import Any

import pytest

from app.bot.nlu.featurizers import spacy_featurizer


@pytest.fixture(autouse=True)
def clear_factory_cache() -> Any:
    """Ensure the shared spaCy factory cache does not leak between tests."""
    spacy_featurizer.SPACY_MODEL_FACTORY._cache.clear()
    yield
    spacy_featurizer.SPACY_MODEL_FACTORY._cache.clear()


@pytest.fixture
def dummy_tokenizer() -> Mock:
    """Provide a callable that simulates a spaCy tokenizer returning a document."""
    tokenizer = Mock(return_value="mock-doc")
    return tokenizer


def test_spacy_model_factory_caches_loaded_models(dummy_tokenizer: Mock) -> None:
    """Verify that SpacyModelFactory.load is invoked only once per model name."""
    model_name = "en_core_web_md"
    spacy_module = types.ModuleType("spacy")
    spacy_module.load = Mock(return_value=dummy_tokenizer)
    sys.modules["spacy"] = spacy_module

    try:
        first_instance = spacy_featurizer.SPACY_MODEL_FACTORY.get(model_name)
        second_instance = spacy_featurizer.SPACY_MODEL_FACTORY.get(model_name)

        assert first_instance is dummy_tokenizer
        assert second_instance is dummy_tokenizer
        spacy_module.load.assert_called_once_with(model_name)
    finally:
        del sys.modules["spacy"]


def test_get_tokenizer_caches_result(monkeypatch: Any, dummy_tokenizer: Mock) -> None:
    """Ensure SpacyFeaturizer._get_tokenizer reuses the cached tokenizer after the first access."""
    factory_get = Mock(return_value=dummy_tokenizer)
    monkeypatch.setattr(spacy_featurizer.SPACY_MODEL_FACTORY, "get", factory_get)

    featurizer = spacy_featurizer.SpacyFeaturizer("en_core_web_sm")
    first = featurizer._get_tokenizer()
    second = featurizer._get_tokenizer()

    assert first is dummy_tokenizer
    assert second is dummy_tokenizer
    factory_get.assert_called_once_with("en_core_web_sm")


def test_process_text_delegates_to_tokenizer(dummy_tokenizer: Mock) -> None:
    """Validate that _process_text forwards the input text to the tokenizer."""
    featurizer = spacy_featurizer.SpacyFeaturizer("en_core_web_sm")
    featurizer._tokenizer = dummy_tokenizer

    processed = featurizer._process_text("hi there")

    assert processed == dummy_tokenizer.return_value
    dummy_tokenizer.assert_called_once_with("hi there")


def test_train_adds_spacy_doc_for_non_empty_examples(monkeypatch: Any) -> None:
    """Confirm training data receives a spacy_doc when text is provided."""
    featurizer = spacy_featurizer.SpacyFeaturizer("en_core_web_sm")
    processed_doc = object()
    monkeypatch.setattr(featurizer, "_process_text", Mock(return_value=processed_doc))

    examples = [
        {"text": "  "},
        {"text": "Hello"},
        {"text": ""},
    ]

    featurizer.train(examples, model_path="unused")

    assert "spacy_doc" not in examples[0]
    assert examples[1]["spacy_doc"] is processed_doc
    assert "spacy_doc" not in examples[2]
    featurizer._process_text.assert_called_once_with("Hello")


def test_process_attaches_spacy_doc(monkeypatch: Any) -> None:
    """Ensure process adds a spaCy document to the message when text exists."""
    featurizer = spacy_featurizer.SpacyFeaturizer("en_core_web_sm")
    processed_doc = object()
    monkeypatch.setattr(featurizer, "_process_text", Mock(return_value=processed_doc))

    message: dict[str, Any] = {"text": "hi"}
    result = featurizer.process(message)

    assert result["spacy_doc"] is processed_doc
    featurizer._process_text.assert_called_once_with("hi")


def test_process_with_missing_text_returns_message() -> None:
    """Validate that processing a message without text leaves it untouched."""
    featurizer = spacy_featurizer.SpacyFeaturizer("en_core_web_sm")

    message: dict[str, Any] = {}
    result = featurizer.process(message)

    assert result == {}


def test_load_always_returns_true() -> None:
    """The load method is a no-op and should always return True."""
    featurizer = spacy_featurizer.SpacyFeaturizer("en_core_web_sm")

    assert featurizer.load(model_path="irrelevant") is True