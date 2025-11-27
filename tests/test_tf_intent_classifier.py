import os
import io
import cloudpickle
import numpy as np
import types
import pytest
from typing import Any, Dict, List

from app.bot.nlu.intent_classifiers import tf_intent_classifer as tf_mod

TfIntentClassifier = tf_mod.TfIntentClassifier


class FakeNlp:
    """A fake spacy-like NLP object that returns a vector of ones."""
    def __init__(self, size: int):
        self._size = size

    def __call__(self, text: str):
        # Return an object with a .vector attribute
        return types.SimpleNamespace(vector=np.ones(self._size, dtype=np.float32))


class MockModel:
    def __init__(self, predict_ret=None):
        self.fit_called = False
        self.saved_path = None
        self.predict_ret = predict_ret

    def fit(self, x, y, **kwargs):
        self.fit_called = True
        # return a dummy History-like object
        return types.SimpleNamespace(history={})

    def save(self, path, save_format=None):
        # record the path where save was invoked
        self.saved_path = path

    def predict(self, x, verbose=0):
        if self.predict_ret is None:
            # Default: uniform probabilities for two classes
            batch = x.shape[0]
            return np.tile(np.array([[0.2, 0.8]]), (batch, 1))
        return self.predict_ret


@pytest.fixture(autouse=True)
def patch_spacy(monkeypatch):
    """Patch spacy.load in the tf module to use a lightweight fake NLP."""
    fake = FakeNlp(tf_mod.TfIntentClassifier.VOCAB_SIZE)
    monkeypatch.setattr(tf_mod, "spacy", types.SimpleNamespace(load=lambda name: fake))
    yield


def test_vectorize_texts_success() -> None:
    """_vectorize_texts should return an array of shape (n_texts, VOCAB_SIZE) using the spacy vectors."""
    clf = TfIntentClassifier(enable_gpu=False)

    texts = ["hello world", "testing"]
    vectors = clf._vectorize_texts(texts)

    assert isinstance(vectors, np.ndarray)
    assert vectors.shape == (2, clf.VOCAB_SIZE)
    # Each vector should be ones as provided by FakeNlp
    assert np.allclose(vectors, np.ones_like(vectors))


def test_vectorize_texts_no_spacy_loaded_raises() -> None:
    """If no spacy model is loaded, _vectorize_texts should raise RuntimeError."""
    clf = TfIntentClassifier(enable_gpu=False)
    clf.nlp = None
    with pytest.raises(RuntimeError):
        clf._vectorize_texts(["text"])


def test_create_model_compilation() -> None:
    """_create_model should return a compiled tf.keras Model with correct output units."""
    clf = TfIntentClassifier(enable_gpu=False)
    model = clf._create_model(num_labels=4)

    # Keras model should have an output shape with last dim equal to num_labels
    assert hasattr(model, "predict")
    assert model.output_shape[-1] == 4


def test_train_with_valid_data_saves_model_and_labels(tmp_path, monkeypatch) -> None:
    """train should vectorize texts, fit the model, save the model and dump labels file."""
    clf = TfIntentClassifier(enable_gpu=False)

    # Patch vectorization to produce tiny x_train
    def fake_vectorize(texts: List[str]):
        return np.zeros((len(texts), clf.VOCAB_SIZE), dtype=np.float32)

    monkeypatch.setattr(clf, "_vectorize_texts", fake_vectorize)

    # Use a MockModel to avoid long training
    mock_model = MockModel()
    monkeypatch.setattr(clf, "_create_model", lambda num: mock_model)

    training_data = [
        {"text": "hi", "intent": "greet"},
        {"text": "hello", "intent": "greet"},
        {"text": "bye", "intent": "goodbye"},
    ]

    model_dir = tmp_path / "model_dir"
    clf.train(training_data, str(model_dir))

    # After training, model attribute should be set and save should have been called
    assert clf.model is mock_model
    assert mock_model.saved_path == os.path.join(str(model_dir), clf.MODEL_NAME)

    # Labels file should exist
    labels_file = os.path.join(str(model_dir), clf.LABELS_NAME)
    assert os.path.exists(labels_file)

    # The label encoder should have classes for 'greet' and 'goodbye'
    assert clf.label_encoder is not None
    assert set(clf.label_encoder.classes_) == {"greet", "goodbye"}


def test_train_with_no_valid_examples_logs_and_returns(monkeypatch) -> None:
    """train should return early without exceptions when there are no valid training examples."""
    clf = TfIntentClassifier(enable_gpu=False)
    # Provide only invalid examples
    training_data = [{"text": "", "intent": None}, {"text": "  ", "intent": ""}]

    # Should not raise
    clf.train(training_data, model_path="")
    assert clf.model is None
    assert clf.label_encoder is None


def test_load_success(tmp_path, monkeypatch) -> None:
    """load should populate model and label_encoder and return True on success."""
    clf = TfIntentClassifier(enable_gpu=False)

    model_dir = tmp_path / "model_dir"
    model_dir.mkdir()

    # Create dummy labels file to allow open(); cloudpickle.load is mocked
    labels_file = model_dir / tf_mod.TfIntentClassifier.LABELS_NAME
    labels_file.write_bytes(b"")

    # Patch tf.keras.models.load_model and cloudpickle.load
    fake_model = MockModel()
    monkeypatch.setattr(tf_mod.tf.keras.models, "load_model", lambda path: fake_model)
    fake_label_encoder = "LABEL_ENCODER"
    monkeypatch.setattr(tf_mod.cloudpickle, "load", lambda f: fake_label_encoder)

    success = clf.load(str(model_dir))
    assert success is True
    assert clf.model is fake_model
    assert clf.label_encoder == fake_label_encoder


def test_load_failure(monkeypatch) -> None:
    """load should return False when model loading raises an exception."""
    clf = TfIntentClassifier(enable_gpu=False)

    # Patch load_model to raise
    monkeypatch.setattr(tf_mod.tf.keras.models, "load_model", lambda path: (_ for _ in ()).throw(RuntimeError("bad")))

    success = clf.load("nonexistent")
    assert success is False


def test_predict_proba_requires_model_and_label_encoder() -> None:
    """predict_proba should raise RuntimeError when model or label encoder missing."""
    clf = TfIntentClassifier(enable_gpu=False)
    clf.model = None
    clf.label_encoder = None
    with pytest.raises(RuntimeError):
        clf.predict_proba(["hello"])


def test_predict_proba_returns_sorted_indices_and_probs(monkeypatch) -> None:
    """predict_proba should return sorted class indices (desc) and raw probabilities."""
    clf = TfIntentClassifier(enable_gpu=False)

    # Patch vectorization to return 2 examples
    monkeypatch.setattr(clf, "_vectorize_texts", lambda texts: np.zeros((len(texts), clf.VOCAB_SIZE), dtype=np.float32))

    # Create predictable predictions for 2 examples and 3 labels
    probs = np.array([[0.1, 0.7, 0.2], [0.9, 0.05, 0.05]])
    mock_model = MockModel(predict_ret=probs)
    clf.model = mock_model

    # Create fake label encoder with classes_
    le = types.SimpleNamespace(classes_=np.array(["a", "b", "c"]))
    clf.label_encoder = le

    sorted_indices, predictions = clf.predict_proba(["one", "two"])

    # Check shapes
    assert predictions.shape == probs.shape
    # For first row, descending order indices should be [1,2,0]
    assert list(sorted_indices[0]) == [1, 2, 0]
    # predictions should match
    assert np.allclose(predictions, probs)


def test_predict_batch_no_model_returns_messages() -> None:
    """predict_batch should return input messages unchanged when model not loaded."""
    clf = TfIntentClassifier(enable_gpu=False)
    clf.model = None

    messages = [{"text": "hi"}, {"text": ""}]
    returned = clf.predict_batch(messages.copy())
    assert returned == messages


def test_predict_batch_updates_messages(monkeypatch) -> None:
    """predict_batch should update messages with intent and intent_ranking for non-empty texts."""
    clf = TfIntentClassifier(enable_gpu=False)

    # Prepare messages with one empty and two valid texts
    messages = [{"text": ""}, {"text": "hello"}, {"text": "bye"}]

    # Patch predict_proba to return predictable sorted indices and probabilities
    sorted_indices = np.array([[1, 0], [0, 1]])
    probs = np.array([[0.75, 0.25], [0.6, 0.4]])
    monkeypatch.setattr(clf, "predict_proba", lambda texts: (sorted_indices, probs))

    # Label encoder classes
    clf.label_encoder = types.SimpleNamespace(classes_=np.array(["intent_a", "intent_b"]))
    clf.model = MockModel()

    updated = clf.predict_batch(messages)

    # Message 1 should be unchanged (empty text)
    assert updated[0].get("intent") is None or updated[0].get("intent") == {"intent": None, "confidence": 0.0}

    # Message 2 should have top intent 'intent_b' (index 1)
    intent2 = updated[1]["intent"]
    assert intent2["intent"] == "intent_b"
    assert isinstance(intent2["confidence"], float)

    # Intent ranking length should be limited by INTENT_RANKING_LENGTH
    assert len(updated[1]["intent_ranking"]) <= clf.INTENT_RANKING_LENGTH


def test_process_empty_and_exception_handling(monkeypatch) -> None:
    """process should handle empty text and exceptions from predict_batch gracefully."""
    clf = TfIntentClassifier(enable_gpu=False)

    # Empty text
    msg = {"text": ""}
    out = clf.process(msg.copy())
    assert out["intent"]["intent"] is None
    assert out["intent"]["confidence"] == 0.0

    # Now simulate exception in predict_batch
    clf.model = MockModel()
    def raise_exc(messages):
        raise RuntimeError("boom")
    monkeypatch.setattr(clf, "predict_batch", raise_exc)

    msg2 = {"text": "hello"}
    out2 = clf.process(msg2.copy())
    assert out2["intent"]["intent"] is None
    assert out2["intent"]["confidence"] == 0.0