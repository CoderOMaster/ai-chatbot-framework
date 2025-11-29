"""Tests for the lazy loader in app.bot.nlu.intent_classifiers.__init__."""
from types import SimpleNamespace

import pytest

import app.bot.nlu.intent_classifiers as intent_classifiers


def test_getattr_lazy_load_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure __getattr__ loads the classifier module only when accessed."""

    classifier_name = next(iter(intent_classifiers._CLASSIFIERS.keys()))
    module_path = intent_classifiers._CLASSIFIERS[classifier_name]

    loaded: dict[str, str] = {}

    def fake_import_module(path: str) -> SimpleNamespace:
        loaded["module"] = path
        return SimpleNamespace(**{classifier_name: "lazy-loaded-object"})

    monkeypatch.setattr("app.bot.nlu.intent_classifiers.import_module", fake_import_module)

    result = intent_classifiers.__getattr__(classifier_name)

    assert result == "lazy-loaded-object"
    assert loaded["module"] == module_path


def test_getattr_unknown_classifier_raises() -> None:
    """Requesting a non-existent classifier should raise AttributeError."""

    random_name = "NonExistingClassifier"

    with pytest.raises(AttributeError) as exc_info:
        intent_classifiers.__getattr__(random_name)

    assert random_name in str(exc_info.value)


def test_dir_returns_sorted_listing() -> None:
    """__dir__ should expose the classifier names alongside module globals."""

    directory = intent_classifiers.__dir__()

    assert isinstance(directory, list)
    assert directory == sorted(directory)
    for classifier in intent_classifiers.__all__:
        assert classifier in directory
    assert "__name__" in directory