import os
import json
import pickle
import numpy as np
import pytest
from types import SimpleNamespace

from app.bot.nlu.intent_classifiers.sklearn_intent_classifer import (
    SklearnIntentClassifier,
    ModelVersion,
    DriftMetrics,
)


class DummySpacyDoc:
    def __init__(self, vector):
        self.vector = np.array(vector)


class FakeModel:
    """Simple fake model that implements predict_proba and fit for tests."""
    def __init__(self, classes=None, probs=None):
        self.classes_ = np.array(classes) if classes is not None else np.array(["a", "b"])
        # default predict_proba returns probs if provided else uniform
        self._probs = (np.array(probs) if probs is not None else np.array([[0.3, 0.7]]))
        self.fitted = False

    def predict_proba(self, X):
        # return a copy shaped to (n_samples, n_classes)
        n = X.shape[0]
        return np.tile(self._probs, (n, 1))

    def fit(self, X, y):
        self.fitted = True
        return self


class FakeGridSearchCV:
    """A fake GridSearchCV used to replace heavy sklearn behavior in tests."""
    def __init__(self, estimator, param_grid, n_jobs, cv, scoring, verbose):
        self.estimator = estimator
        self.param_grid = param_grid
        self.n_jobs = n_jobs
        self.cv = cv
        self.scoring = scoring
        self.verbose = verbose
        self.best_score_ = 0.95
        self.best_estimator_ = FakeModel(classes=["greet", "bye"], probs=[[0.1, 0.9]])

    def fit(self, X, y):
        # pretend to search and pick best estimator
        return self


class FakeCalibrator:
    def __init__(self, model, method, cv):
        self.model = model
        self.method = method
        self.cv = cv

    def fit(self, X, y):
        # pretend calibration succeeded
        return self

    def predict_proba(self, X):
        # return slightly smoothed probabilities
        base = self.model.predict_proba(X)
        return base * 0.9 + 0.05


@pytest.fixture
def classifier():
    return SklearnIntentClassifier()


def test_generate_version_id_consistency():
    """Ensure that version id generation is deterministic for same training data."""
    c = SklearnIntentClassifier()
    data = [
        {"intent": "a", "text": "hello"},
        {"intent": "b", "text": "world!"},
    ]
    vid1 = c._generate_version_id(data)
    vid2 = c._generate_version_id(data)
    assert isinstance(vid1, str)
    assert len(vid1) == 12
    assert vid1 == vid2


def test_get_model_path_with_and_without_version():
    """Model path should include version when provided and 'latest' otherwise."""
    c = SklearnIntentClassifier()
    p1 = c._get_model_path("/tmp/models", "abc123")
    assert p1.endswith("sklearn_intent_model_vabc123.pkl")
    p2 = c._get_model_path("/tmp/models")
    assert p2.endswith("sklearn_intent_model_vlatest.pkl")


def test_save_and_load_metadata(tmp_path):
    """Saving metadata writes a file and loading restores model versions."""
    c = SklearnIntentClassifier()
    # populate versions and drift metrics
    mv = ModelVersion(version_id="v1", timestamp="t", training_samples=10, accuracy=0.8, is_active=True)
    c.model_version = mv
    c.model_versions[mv.version_id] = mv
    dm = DriftMetrics(timestamp="t2", prediction_entropy=0.5, confidence_mean=0.7, confidence_std=0.1, class_distribution_change=0.0)
    c.drift_metrics.append(dm)

    model_dir = str(tmp_path)
    c._save_metadata(model_dir)

    # Ensure file written
    metadata_path = os.path.join(model_dir, c.METADATA_FILE)
    assert os.path.exists(metadata_path)

    # Load into new classifier
    c2 = SklearnIntentClassifier()
    c2._load_metadata(model_dir)
    assert c2.model_version is not None
    assert "v1" in c2.model_versions


def test_calibrate_model_with_monkeypatch(monkeypatch):
    """Calibration should instantiate CalibratedClassifierCV and assign calibrator."""
    c = SklearnIntentClassifier()
    # Set a fake underlying model
    c.model = FakeModel(classes=["a", "b"], probs=[[0.2, 0.8]])

    # Monkeypatch CalibratedClassifierCV in the module to our FakeCalibrator
    monkeypatch.setattr(
        "app.bot.nlu.intent_classifiers.sklearn_intent_classifer.CalibratedClassifierCV",
        FakeCalibrator,
    )

    # Create dummy X,y
    X = np.random.rand(6, 4)
    y = np.array(["a", "a", "b", "b", "a", "b"])

    c._calibrate_model(X, y)
    assert c.calibrator is not None
    # Ensure calibrator holds our model
    assert isinstance(c.calibrator, FakeCalibrator)


def test_update_drift_metrics_and_trimming():
    """Drift metrics should accumulate and be trimmed to last 100 entries."""
    c = SklearnIntentClassifier()
    # create a small probability vector
    probs = np.array([[0.2, 0.8]])
    preds = np.array([1])
    # call many times to exceed 100 entries
    for _ in range(105):
        c._update_drift_metrics(probs, preds)
    assert len(c.drift_metrics) == 100

    # empty probabilities should not change metrics
    before = len(c.drift_metrics)
    c._update_drift_metrics(np.array([]), np.array([]))
    assert len(c.drift_metrics) == before


def test_get_spacy_embedding():
    """Embedding extraction returns numpy array from spacy doc."""
    doc = DummySpacyDoc([1.0, 2.0, 3.0])
    c = SklearnIntentClassifier()
    emb = c.get_spacy_embedding(doc)
    assert isinstance(emb, np.ndarray)
    assert emb.shape == (3,)


def test_train_creates_files_and_metadata(tmp_path, monkeypatch):
    """Training should write model files and metadata; uses monkeypatched GridSearchCV."""
    c = SklearnIntentClassifier()

    # Monkeypatch GridSearchCV to avoid heavy sklearn operations
    monkeypatch.setattr(
        "app.bot.nlu.intent_classifiers.sklearn_intent_classifer.GridSearchCV",
        FakeGridSearchCV,
    )

    # Patch calibrate to a no-op to avoid heavy fitting
    monkeypatch.setattr(
        "app.bot.nlu.intent_classifiers.sklearn_intent_classifer.SklearnIntentClassifier._calibrate_model",
        lambda self, X, y: setattr(self, "calibrator", None),
    )

    # Create simple training data
    docs = [DummySpacyDoc([0.1, 0.2, 0.3, 0.4]) for _ in range(8)]
    training_data = []
    intents = ["greet", "greet", "bye", "greet", "bye", "bye", "greet", "bye"]
    for i, doc in enumerate(docs):
        training_data.append({"text": f"t{i}", "spacy_doc": doc, "intent": intents[i]})

    model_dir = str(tmp_path)
    c.train(training_data, model_dir)

    # Ensure metadata exists and classifier updated
    metadata_path = os.path.join(model_dir, c.METADATA_FILE)
    assert os.path.exists(metadata_path)
    assert c.model_version is not None
    assert c._is_loaded is True


def test_load_and_load_version(tmp_path, monkeypatch):
    """Saving fake model files and metadata should be loadable by load and load_version."""
    c = SklearnIntentClassifier()

    # Prepare a fake model file to load
    model_dir = str(tmp_path)
    os.makedirs(model_dir, exist_ok=True)
    fake_model = FakeModel(classes=["x", "y"], probs=[[0.6, 0.4]])

    version_id = "ver123"
    model_file = os.path.join(model_dir, c.MODEL_NAME_TEMPLATE.format(version_id))
    latest_file = os.path.join(model_dir, c.MODEL_NAME_TEMPLATE.format("latest"))
    with open(model_file, "wb") as f:
        # use pickle for our FakeModel
        pickle.dump(fake_model, f)
    with open(latest_file, "wb") as f:
        pickle.dump(fake_model, f)

    # create metadata referencing version
    mv = ModelVersion(version_id=version_id, timestamp="t", training_samples=5, accuracy=0.9, is_active=True)
    c.model_versions[version_id] = mv
    c.model_version = mv
    c._save_metadata(model_dir)

    # Now loading should succeed
    assert c.load(model_dir) is True
    # Load a specific version
    assert c.load_version(model_dir, version_id) is True
    # Loading missing version should return False
    assert c.load_version(model_dir, "nope") is False


def test_partial_fit_behavior(monkeypatch):
    """Partial fit should be a no-op when model unset and call fit when present."""
    c = SklearnIntentClassifier()

    # Without model should be no-op
    c.partial_fit([{"text": "hi", "spacy_doc": DummySpacyDoc([0.1, 0.2]), "intent": "a"}])

    # Set fake model with fit
    fm = FakeModel(classes=["a", "b"], probs=[[0.2, 0.8]])
    c.model = fm

    # Patch calibrate model to no-op
    monkeypatch.setattr(
        "app.bot.nlu.intent_classifiers.sklearn_intent_classifer.SklearnIntentClassifier._calibrate_model",
        lambda self, X, y: setattr(self, "calibrator", None),
    )

    c.partial_fit([
        {"text": "hello", "spacy_doc": DummySpacyDoc([0.1, 0.2, 0.3, 0.4]), "intent": "a"},
        {"text": "bye", "spacy_doc": DummySpacyDoc([0.2, 0.1, 0.3, 0.4]), "intent": "b"},
    ])

    assert fm.fitted is True


def test_predict_proba_and_process(monkeypatch):
    """predict_proba should return empty arrays when no model; process should handle normal and error cases."""
    c = SklearnIntentClassifier()

    # No model
    idxs, probs = c.predict_proba({})
    assert idxs.size == 0
    assert probs.size == 0

    # With model (no calibrator)
    fm = FakeModel(classes=["a", "b"], probs=[[0.25, 0.75]])
    c.model = fm
    msg = {"text": "hi", "spacy_doc": DummySpacyDoc([0.1, 0.2, 0.3, 0.4])}

    idxs, probs = c.predict_proba(msg)
    # indices should be shape (1, n_classes)
    assert idxs.shape[0] == 1
    assert probs.shape[0] == 1

    # process should populate intent and ranking
    out = c.process(msg.copy())
    assert "intent" in out
    assert "intent_ranking" in out
    assert out["intent"]["name"] in fm.classes_

    # Force predict to raise and ensure process handles it
    class BadModel:
        def predict_proba(self, X):
            raise RuntimeError("boom")

    c.model = BadModel()
    out2 = c.process({"text": "hello", "spacy_doc": DummySpacyDoc([0.1, 0.2])})
    assert out2["intent"]["name"] is None
    assert out2["intent_ranking"] == []


def test_get_drift_report_and_model_info():
    """get_drift_report should return 'no_data' when empty and valid stats when metrics exist."""
    c = SklearnIntentClassifier()
    # No metrics
    assert c.get_drift_report()["status"] == "no_data"

    # Add some drift metrics and prediction history
    for i in range(3):
        dm = DriftMetrics(timestamp=f"t{i}", prediction_entropy=0.1 * (i + 1), confidence_mean=0.8 - 0.05 * i, confidence_std=0.01 * i, class_distribution_change=0.0)
        c.drift_metrics.append(dm)
        c.prediction_history.append(("a", 0.8))

    report = c.get_drift_report()
    assert report["status"] == "ok"
    assert report["total_predictions"] == 3

    info = c.get_model_info()
    assert "is_loaded" in info
    assert "available_versions" in info
    assert info["drift_metrics_count"] == len(c.drift_metrics)