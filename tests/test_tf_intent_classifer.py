import builtins
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Generator, List, Tuple

import cloudpickle
import numpy as np
import pytest
from sklearn.preprocessing import LabelBinarizer

from app.bot.nlu.intent_classifiers import tf_intent_classifer as mod
from app.bot.nlu.intent_classifiers.tf_intent_classifer import (  # noqa: WPS214
    TfIntentClassifier,
    _get_tf_module,
)


class FakeTFModule:
    """Minimal mock of the TensorFlow module surface required by the classifier."""

    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.clear_sessions = 0
        self.loaded_paths: List[Tuple[str, bool]] = []

        self.keras = SimpleNamespace(
            backend=SimpleNamespace(clear_session=self._clear_session),
            models=SimpleNamespace(
                load_model=self._load_model,
                save_model=lambda *args, **kwargs: None,
            ),
        )

    def _clear_session(self) -> None:
        self.clear_sessions += 1

    def _load_model(self, path: str, compile: bool) -> dict:
        if self.should_fail:
            raise RuntimeError("unable to load model")
        self.loaded_paths.append((path, compile))
        return {"model": "loaded"}


@pytest.fixture(autouse=True)
def reset_tf_module() -> Generator[None, None, None]:
    """Ensure the lazy TensorFlow cache does not leak state across tests."""
    previous = mod._TF_MODULE
    mod._TF_MODULE = None
    yield
    mod._TF_MODULE = previous


@pytest.fixture
def dummy_nlp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the spaCy loader so that classifier initialization is cheap."""

    class DummyDoc:
        def __init__(self) -> None:
            self.vector = np.ones(384, dtype=np.float32)

    class DummyNLP:
        def __call__(self, text: str) -> DummyDoc:
            return DummyDoc()

    monkeypatch.setattr(mod.spacy, "load", lambda _: DummyNLP())


@pytest.fixture
def classifier(dummy_nlp: None) -> TfIntentClassifier:
    """Instantiate the TensorFlow intent classifier with a patched NLP pipeline."""
    return TfIntentClassifier()


def test_get_tf_module_lazy_imports_tensorflow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify TensorFlow is imported lazily and cached by the helper."""
    fake_tf = SimpleNamespace(name="tensorflow")
    imported: List[str] = []
    original_import = builtins.__import__

    def fake_import(name: str, globals: Any = None, locals: Any = None, fromlist: Tuple[str, ...] = (), level: int = 0) -> Any:
        if name == "tensorflow":
            imported.append(name)
            return fake_tf
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    mod._TF_MODULE = None

    tf_module = _get_tf_module()

    assert tf_module is fake_tf
    assert imported == ["tensorflow"]


def test_get_tf_module_returns_cached_without_reimport(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure cached TensorFlow module instances are reused without extra imports."""
    fake_tf = SimpleNamespace(name="cached_tf")
    mod._TF_MODULE = fake_tf

    def raising_import(name: str, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("TensorFlow should not be re-imported when cached")

    monkeypatch.setattr(builtins, "__import__", raising_import)

    tf_module = _get_tf_module()

    assert tf_module is fake_tf


def test_predict_proba_requires_model_loaded(classifier: TfIntentClassifier) -> None:
    """Predict proba must fail if the underlying TensorFlow model is unavailable."""
    with pytest.raises(RuntimeError):
        classifier.predict_proba({"text": "hello"})


def test_predict_proba_returns_sorted_indices_and_probabilities(classifier: TfIntentClassifier) -> None:
    """Predicting probabilities yields descending intent indices and matching scores."""

    class DummyModel:
        def predict(self, _: np.ndarray) -> np.ndarray:
            return np.array([[0.1, 0.9, 0.4]], dtype=np.float32)

    classifier.model = DummyModel()

    sorted_indices, probabilities = classifier.predict_proba({"text": "greetings"})

    np.testing.assert_array_equal(sorted_indices, np.array([[1, 2, 0]]))
    np.testing.assert_allclose(
        probabilities.flatten(),
        np.array([0.9, 0.4, 0.1], dtype=np.float32),
    )


def test_process_skips_empty_text(classifier: TfIntentClassifier) -> None:
    """Messages without text are returned untouched by the classifier."""
    original_message: dict = {}

    processed = classifier.process(original_message)

    assert processed is original_message
    assert processed == {}


def test_process_populates_intent_and_ranking(monkeypatch: pytest.MonkeyPatch, classifier: TfIntentClassifier) -> None:
    """The classifier populates intent and ranking details for valid messages."""
    classifier.model = object()
    classifier.label_encoder.classes_ = np.array(["greet", "farewell", "affirm"])

    sorted_indices = np.array([[1, 0, 2]])
    probabilities = np.array([[[0.7], [0.2], [0.1]]], dtype=np.float32)

    monkeypatch.setattr(
        classifier,
        "predict_proba",
        lambda message: (sorted_indices, probabilities),
    )

    message = {"text": "hello"}
    processed = classifier.process(message)

    assert processed["intent"]["intent"] == "farewell"
    assert pytest.approx(processed["intent"]["confidence"]) == 0.7
    expected_ranking = [
        {"intent": "farewell", "confidence": 0.7},
        {"intent": "greet", "confidence": 0.2},
        {"intent": "affirm", "confidence": 0.1},
    ]
    assert processed["intent_ranking"] == expected_ranking


def test_load_returns_true_and_initializes_model_and_labels(tmp_path: Path, classifier: TfIntentClassifier) -> None:
    """Loading succeeds when model and label artefacts exist and TF loads cleanly."""
    tf_stub = FakeTFModule()
    mod._TF_MODULE = tf_stub

    model_dir = tmp_path / "model_dir"
    model_dir.mkdir()
    model_file = model_dir / TfIntentClassifier.MODEL_NAME
    model_file.write_text("stub model content")

    label_encoder = LabelBinarizer()
    label_encoder.fit(["greet", "bye"])
    labels_file = model_dir / TfIntentClassifier.LABELS_NAME
    with open(labels_file, "wb") as label_handle:
        cloudpickle.dump(label_encoder, label_handle)

    success = classifier.load(str(model_dir))

    assert success
    assert classifier.model == {"model": "loaded"}
    assert tuple(classifier.label_encoder.classes_) == tuple(label_encoder.classes_)
    assert tf_stub.loaded_paths == [(str(model_file), True)]
    assert tf_stub.clear_sessions == 1


def test_load_returns_false_when_model_loading_fails(tmp_path: Path, classifier: TfIntentClassifier) -> None:
    """Load returns False if TensorFlow raises during model loading."""
    tf_stub = FakeTFModule(should_fail=True)
    mod._TF_MODULE = tf_stub

    model_dir = tmp_path / "model_dir"
    model_dir.mkdir()
    model_file = model_dir / TfIntentClassifier.MODEL_NAME
    model_file.write_text("broken content")

    result = classifier.load(str(model_dir))

    assert result is False
    assert classifier.model is None
    assert tf_stub.loaded_paths == []


# Ensure __all__ only exports classifier class

def test_module_exports_only_classifier() -> None:
    """The module exports only the TfIntentClassifier from its namespace."""
    assert mod.__all__ == ["TfIntentClassifier"]