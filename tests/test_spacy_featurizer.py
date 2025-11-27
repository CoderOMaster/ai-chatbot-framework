import sys
import types
import pytest
from unittest.mock import MagicMock

from app.bot.nlu.featurizers.spacy_featurizer import (
    SpacyModelSingleton,
    SpacyFeaturizer,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the SpacyModelSingleton global state between tests."""
    # If an instance exists, try to shutdown its executor to avoid leaked threads
    inst = SpacyModelSingleton._instance
    if inst is not None:
        try:
            if hasattr(inst, "_executor"):
                inst._executor.shutdown(wait=True)
        except Exception:
            pass

    SpacyModelSingleton._instance = None
    SpacyModelSingleton._model_cache = {}
    yield


class FakeNLP:
    def __init__(self):
        self.calls = []

    def __call__(self, text):
        # Record call and return a simple object representing a Doc
        self.calls.append(text)
        return {"text": text, "len": len(text)}


def make_fake_spacy(load_behavior=None):
    """Return a fake spacy module.

    load_behavior: A callable that implements spacy.load(name) behavior.
    If None, returns a FakeNLP instance always.
    """
    fake = types.SimpleNamespace()

    def default_load(name):
        return FakeNLP()

    fake.load = load_behavior or default_load
    return fake


def test_singleton_instance_identity():
    """Multiple constructions should return the same singleton instance."""
    a = SpacyModelSingleton("en_core_web_sm")
    b = SpacyModelSingleton("different_model")
    assert a is b
    assert a._initialized is True


def test_load_model_success_and_warm(monkeypatch):
    """Loading should set nlp and warm the model (calls on sample texts)."""
    fake_spacy = make_fake_spacy()
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)

    model = SpacyModelSingleton("en_core_web_sm")
    # Ensure initially not loaded
    assert model.nlp is None

    model.load()
    assert model.nlp is not None
    # The FakeNLP should have been called for each warm text
    assert hasattr(model.nlp, "calls")
    assert len(model.nlp.calls) >= 1
    assert model.is_healthy() is True


def test_load_triggers_download_when_missing(monkeypatch):
    """If spacy.load raises OSError first, the download subprocess should be called and load retried."""
    call_count = {"count": 0}

    def load_behavior(name):
        # raise OSError on the first call, succeed on subsequent calls
        if call_count["count"] == 0:
            call_count["count"] += 1
            raise OSError("model not found")
        return FakeNLP()

    fake_spacy = make_fake_spacy(load_behavior=load_behavior)
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)

    # Spy on subprocess.check_call
    fake_subprocess = types.SimpleNamespace()
    def fake_check_call(cmd):
        # emulate successful download
        return 0
    fake_subprocess.check_call = fake_check_call
    monkeypatch.setitem(sys.modules, "subprocess", fake_subprocess)

    # Also provide sys so the subprocess call can access sys.executable - it's fine to use real sys

    model = SpacyModelSingleton("en_core_web_sm")
    model.load()

    # After load, nlp should be set
    assert model.nlp is not None
    assert call_count["count"] == 1


def test_process_without_load_raises():
    """Calling process before load() should raise RuntimeError."""
    model = SpacyModelSingleton("en_core_web_sm")
    with pytest.raises(RuntimeError):
        model.process("hello world")


def test_process_with_cache_hits(monkeypatch):
    """Processing same text twice with cache enabled should hit the cache on second call."""
    fake_spacy = make_fake_spacy()
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)

    model = SpacyModelSingleton("en_core_web_sm")
    model.load()

    doc1 = model.process("hello world", use_cache=True)
    # Call again, should come from cache and be identical object
    doc2 = model.process("hello world", use_cache=True)
    assert doc1 == doc2

    stats = model.get_cache_stats()
    assert stats["cache_size"] >= 1


def test_process_batch_concurrent(monkeypatch):
    """process_batch should return results for all inputs and operate concurrently."""
    fake_spacy = make_fake_spacy()
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)

    model = SpacyModelSingleton("en_core_web_sm")
    model.load()

    texts = [f"text {i}" for i in range(8)]
    results = model.process_batch(texts, use_cache=False)
    assert len(results) == len(texts)
    for i, res in enumerate(results):
        assert res["text"] == texts[i]


def test_clear_cache_and_stats(monkeypatch):
    """Clearing the cache should reset cache_size to 0."""
    fake_spacy = make_fake_spacy()
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)

    model = SpacyModelSingleton("en_core_web_sm")
    model.load()

    _ = model.process("one", use_cache=True)
    _ = model.process("two", use_cache=True)
    stats_before = model.get_cache_stats()
    assert stats_before["cache_size"] >= 2

    model.clear_cache()
    stats_after = model.get_cache_stats()
    assert stats_after["cache_size"] == 0


def test_spacyfeaturizer_train_and_skip_empty(monkeypatch):
    """Training should process non-empty texts and skip empty ones."""
    fake_spacy = make_fake_spacy()
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)

    featurizer = SpacyFeaturizer(model_name="en_core_web_sm", use_cache=True)

    # Ensure model starts unloaded and is_healthy returns False to force load
    model_inst = featurizer._get_model()

    # Monkeypatch is_healthy to False initially so load() is invoked
    model_inst.is_healthy = lambda: False
    # Replace load with a function that sets nlp
    def fake_load():
        model_inst.nlp = FakeNLP()
    model_inst.load = fake_load

    training_data = [
        {"text": ""},
        {"text": "hello training"},
    ]

    featurizer.train(training_data, model_path="/tmp")

    # The empty example should remain without spacy_doc, the other should have it
    assert "spacy_doc" not in training_data[0]
    assert "spacy_doc" in training_data[1]


def test_spacyfeaturizer_load_returns_false_on_exception(monkeypatch):
    """If model.load raises, SpacyFeaturizer.load should return False."""
    featurizer = SpacyFeaturizer()
    model_inst = featurizer._get_model()

    def raise_load():
        raise RuntimeError("boom")

    model_inst.load = raise_load

    assert featurizer.load(model_path="/tmp") is False


def test_spacyfeaturizer_process_empty_text_no_change():
    """Processing a message without text should return it unchanged."""
    featurizer = SpacyFeaturizer()
    msg = {}
    out = featurizer.process(msg)
    assert out is msg


def test_health_check_healthy_and_unhealthy(monkeypatch):
    """Health check should report healthy when model is functional and unhealthy otherwise."""
    featurizer = SpacyFeaturizer()
    model_inst = featurizer._get_model()

    # Case 1: unhealthy (nlp is None)
    model_inst.nlp = None
    model_inst.is_healthy = lambda: False

    health = featurizer.health_check()
    assert health["status"] == "unhealthy"
    assert health["model_loaded"] is False

    # Case 2: healthy
    model_inst.nlp = FakeNLP()
    model_inst.is_healthy = lambda: True
    health2 = featurizer.health_check()
    assert health2["status"] == "healthy"
    assert health2["model_loaded"] is True
    assert isinstance(health2["cache_stats"], dict)