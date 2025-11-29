from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Dict

import cloudpickle
import numpy as np
import pytest

from app.bot.nlu.intent_classifiers.sklearn_intent_classifer import (
    SklearnIntentClassifier,
    SklearnIntentClassifierConfig,
)


class DummyDoc:
    def __init__(self, vector: np.ndarray) -> None:
        self.vector = vector


@pytest.fixture
def simple_spacy_doc() -> DummyDoc:
    """Provide a basic spaCy doc replacement for vector extraction."""
    return DummyDoc(np.array([1.0, 0.0, -0.5]))


def test_model_full_path_creates_directory_and_respects_config(tmp_path: Path) -> None:
    """_model_full_path should honor the configured paths and create missing directories."""
    config = SklearnIntentClassifierConfig(model_path=str(tmp_path), model_name="model.pkl")
    classifier = SklearnIntentClassifier(config=config)

    returned_path = classifier._model_full_path()

    assert Path(returned_path).parent.exists()
    assert returned_path == str(tmp_path / "model.pkl")

    custom_root = tmp_path / "custom"
    override_path = classifier._model_full_path(override_path=str(custom_root))
    assert Path(override_path).parent == custom_root
    assert custom_root.exists()


def test_get_spacy_embedding_returns_numpy_array(simple_spacy_doc: DummyDoc) -> None:
    """Ensure get_spacy_embedding returns the numpy representation of a spaCy doc vector."""
    classifier = SklearnIntentClassifier()
    embedding = classifier.get_spacy_embedding(simple_spacy_doc)
    assert isinstance(embedding, np.ndarray)
    np.testing.assert_allclose(embedding, np.array([1.0, 0.0, -0.5]))


def test_train_raises_with_no_valid_examples() -> None:
    """Training without valid examples should raise a ValueError."""
    classifier = SklearnIntentClassifier()
    bad_data = [
        {"text": "   ", "spacy_doc": DummyDoc(np.array([0.0])), "intent": "skip"},
    ]

    with pytest.raises(ValueError, match="Training data must contain at least one valid example."):
        classifier.train(training_data=bad_data)


def test_train_persists_best_estimator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Training should serialize the estimator to disk and update the classifier state."""
    trained_model: Dict[str, Any] = {"marker": "trained-estimator"}

    class DummyGridSearchCV:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.best_estimator_ = trained_model
            self.fit_args: tuple[np.ndarray, list[str]]

        def fit(self, embeddings: np.ndarray, y: list[str]) -> "DummyGridSearchCV":
            self.fit_args = (embeddings, y)
            return self

    sklearn_module = ModuleType("sklearn")
    model_selection_module = ModuleType("sklearn.model_selection")
    model_selection_module.GridSearchCV = DummyGridSearchCV
    svm_module = ModuleType("sklearn.svm")
    svm_module.SVC = lambda *args, **kwargs: SimpleNamespace()

    sklearn_module.model_selection = model_selection_module
    sklearn_module.svm = svm_module

    monkeypatch.setitem(sys.modules, "sklearn", sklearn_module)
    monkeypatch.setitem(sys.modules, "sklearn.model_selection", model_selection_module)
    monkeypatch.setitem(sys.modules, "sklearn.svm", svm_module)

    config = SklearnIntentClassifierConfig(model_path=str(tmp_path), model_name="trained.pkl")
    classifier = SklearnIntentClassifier(config=config)

    training_data = [
        {"text": "hello", "spacy_doc": DummyDoc(np.array([1.0, 0.0])), "intent": "greet"},
        {"text": "bye", "spacy_doc": DummyDoc(np.array([0.0, 1.0])), "intent": "farewell"},
        {"text": "hello again", "spacy_doc": DummyDoc(np.array([1.0, 1.0])), "intent": "greet"},
    ]

    classifier.train(training_data=training_data, output_path=str(tmp_path))

    assert classifier.model is trained_model

    saved_path = Path(tmp_path) / "trained.pkl"
    assert saved_path.exists()

    with open(saved_path, "rb") as saved_file:
        loaded_model = cloudpickle.load(saved_file)
    assert loaded_model == trained_model


def test_load_returns_true_and_sets_model(tmp_path: Path) -> None:
    """Loading should succeed when the serialized model exists."""
    config = SklearnIntentClassifierConfig(model_path=str(tmp_path), model_name="saved.pkl")
    classifier = SklearnIntentClassifier(config=config)

    preexisting_model = {"hello": "world"}
    path = classifier._model_full_path()
    with open(path, "wb") as model_file:
        cloudpickle.dump(preexisting_model, model_file)

    result = classifier.load()

    assert result is True
    assert classifier.model == preexisting_model


def test_load_returns_false_when_model_is_missing(tmp_path: Path) -> None:
    """Failure to find the serialized file should return False without raising."""
    config = SklearnIntentClassifierConfig(model_path=str(tmp_path), model_name="missing.pkl")
    classifier = SklearnIntentClassifier(config=config)

    result = classifier.load()

    assert result is False
    assert classifier.model is None


def test_predict_proba_raises_when_model_missing(simple_spacy_doc: DummyDoc) -> None:
    """Predict proba should guard against inference without a loaded model."""
    classifier = SklearnIntentClassifier()

    with pytest.raises(RuntimeError, match=r"Model is not loaded; call load\(\) before prediction\."):
        classifier.predict_proba({"spacy_doc": simple_spacy_doc})


def test_predict_proba_sorts_inferences(simple_spacy_doc: DummyDoc) -> None:
    """Predict proba should return sorted indices and corresponding probabilities."""

    class DummyModel:
        def __init__(self) -> None:
            self.classes_ = np.array(["first", "second", "third"])

        def predict_proba(self, embeddings: list[np.ndarray]) -> np.ndarray:
            return np.array([[0.2, 0.8, 0.5]])

    classifier = SklearnIntentClassifier(model=DummyModel())
    sorted_indices, probabilities = classifier.predict_proba({"spacy_doc": simple_spacy_doc})

    np.testing.assert_array_equal(sorted_indices, np.array([[1, 2, 0]]))
    # Flatten the probabilities to get the expected shape (1, 3)
    np.testing.assert_allclose(probabilities.reshape(1, -1), np.array([[0.8, 0.5, 0.2]]))


def test_process_skips_when_text_or_doc_missing() -> None:
    """Process should leave the message untouched when text or embeddings are absent."""
    classifier = SklearnIntentClassifier()
    message = {"text": "", "spacy_doc": None}

    processed = classifier.process(message)

    assert processed is message
    assert "intent" not in processed
    assert "intent_ranking" not in processed


def test_process_builds_intent_ranking(monkeypatch: pytest.MonkeyPatch) -> None:
    """Process should populate intent data when a model is configured."""
    classifier = SklearnIntentClassifier()
    classifier.model = SimpleNamespace(classes_=np.array(["alpha", "beta", "gamma"]))

    def fake_predict_proba(_: Dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
        return np.array([[2, 0, 1]]), np.array([[0.6, 0.3, 0.1]])

    monkeypatch.setattr(classifier, "predict_proba", fake_predict_proba)

    message = {"text": "hi", "spacy_doc": DummyDoc(np.array([0.1])), "intent": None}
    result = classifier.process(message)

    assert result["intent"]["intent"] == "gamma"
    assert pytest.approx(result["intent"]["confidence"]) == 0.6
    ranking = result["intent_ranking"]
    assert len(ranking) == 3
    assert ranking[0] == {"intent": "gamma", "confidence": 0.6}
    assert ranking[1] == {"intent": "alpha", "confidence": 0.3}
    assert ranking[2] == {"intent": "beta", "confidence": 0.1}


def test_process_limits_intent_ranking_length(monkeypatch: pytest.MonkeyPatch) -> None:
    """Process should never exceed INTENT_RANKING_LENGTH even if more candidates exist."""
    classifier = SklearnIntentClassifier()
    classifier.model = SimpleNamespace(classes_=np.array(["a", "b", "c", "d"]))

    def fake_predict_proba(_: Dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
        return np.array([[3, 2, 1, 0]]), np.array([[0.9, 0.8, 0.7, 0.6]])

    monkeypatch.setattr(classifier, "predict_proba", fake_predict_proba)

    message = {"text": "test", "spacy_doc": DummyDoc(np.array([0.5]))}
    result = classifier.process(message)

    assert len(result["intent_ranking"]) == classifier.INTENT_RANKING_LENGTH
    intents = [entry["intent"] for entry in result["intent_ranking"]]
    assert intents == ["d", "c", "b"]