import os
import json
import hashlib
import pytest
from typing import List

from app.bot.nlu.entity_extractors import crf_entity_extractor as module
from app.bot.nlu.entity_extractors.crf_entity_extractor import (
    CRFEntityExtractor,
    MODEL_NAME,
    MODEL_METADATA_NAME,
    DEFAULT_CONFIDENCE_THRESHOLD,
)


class FakeToken:
    def __init__(self, text: str, tag_: str, i: int, start: int = 0, end: int = 0):
        self.text = text
        self.tag_ = tag_
        self.i = i
        self.start = start
        self.end = end


class FakeDoc:
    def __init__(self, tokens: List[FakeToken]):
        self._tokens = tokens
        # construct text with spaces to be more realistic
        self.text = " ".join([t.text for t in tokens])

    def __iter__(self):
        for t in self._tokens:
            yield t

    def __len__(self):
        return len(self._tokens)

    def char_span(self, begin: int, end: int):
        # Return tokens that overlap with the char offsets [begin, end)
        span = [t for t in self._tokens if not (t.end <= begin or t.start >= end)]
        return span if span else None


class DummyTrainer:
    def __init__(self, verbose=False):
        self.appended = []
        self.params = None

    def append(self, xseq, yseq):
        self.appended.append((xseq, yseq))

    def set_params(self, params):
        self.params = params

    def train(self, path):
        # create a dummy model file to simulate training output
        with open(path, "w") as f:
            f.write("dummy model")


class DummyTagger:
    def __init__(self, marginal_value: float = 0.8, tag_return: List[str] = None, fail_tag: bool = False):
        self._marginal = marginal_value
        self._tag_return = tag_return or []
        self._fail_tag = fail_tag
        self.opened = False

    def open(self, path):
        self.opened = True

    def tag(self, features):
        if self._fail_tag:
            raise Exception("tag failure")
        return self._tag_return

    def marginal(self, label, idx):
        if isinstance(self._marginal, Exception):
            raise self._marginal
        return self._marginal


@pytest.fixture(autouse=True)
def patch_pycrfsuite(monkeypatch):
    # Patch the pycrfsuite Trainer and Tagger used in the module
    monkeypatch.setattr(module, "pycrfsuite", type("m", (), {})())
    setattr(module.pycrfsuite, "Trainer", DummyTrainer)
    setattr(module.pycrfsuite, "Tagger", DummyTagger)
    yield


@pytest.fixture
def extractor() -> CRFEntityExtractor:
    return CRFEntityExtractor()


def test_extract_features_bos_eos():
    """Verify features include BOS at start and EOS at end and neighboring token features."""
    sent = [("Hello", "NNP"), ("World", "NNP")]
    features0 = CRFEntityExtractor().extract_features(sent, 0)
    features1 = CRFEntityExtractor().extract_features(sent, 1)

    assert "BOS" in features0
    assert "EOS" in features1
    assert any(f.startswith("+1:word.lower=") for f in features0)
    assert any(f.startswith("-1:word.lower=") for f in features1)


def test_sent_to_features_and_labels():
    sent = [("Hi", "UH"), ("there", "RB")]
    features = CRFEntityExtractor().sent_to_features(sent)
    assert isinstance(features, list)
    assert len(features) == 2

    labeled_sent = [("Hi", "UH", "O"), ("there", "RB", "B-LOC")]
    labels = CRFEntityExtractor().sent_to_labels(labeled_sent)
    assert labels == ["O", "B-LOC"]


def test_generate_model_version_consistent():
    data = [{"a": 1}, {"b": 2}]
    v1 = CRFEntityExtractor()._generate_model_version(data)
    v2 = CRFEntityExtractor()._generate_model_version(data)
    assert isinstance(v1, str) and len(v1) == 8
    assert v1 == v2


def test_save_and_load_metadata(tmp_path, extractor: CRFEntityExtractor):
    model_dir = tmp_path / "modeldir"
    model_dir.mkdir()
    extractor._save_metadata(str(model_dir), "v1", 5)

    metadata_path = model_dir / MODEL_METADATA_NAME
    assert metadata_path.exists()

    # Now load via _load_metadata
    loaded = extractor._load_metadata(str(model_dir))
    assert loaded is True
    assert extractor.model_metadata.get("version") is not None


def test_validate_model_checks():
    ex = CRFEntityExtractor()
    valid, msg = ex._validate_model()
    assert valid is False
    assert msg == "Tagger not initialized"

    # Now with a tagger that succeeds
    ex.tagger = DummyTagger(tag_return=["O"], marginal_value=0.5)
    valid2, msg2 = ex._validate_model()
    assert valid2 is True
    assert msg2 is None

    # Tagger.tag raises -> validation fails
    ex.tagger = DummyTagger(fail_tag=True)
    valid3, msg3 = ex._validate_model()
    assert valid3 is False
    assert msg3 and "Model validation failed" in msg3


def test_train_empty_raises(extractor: CRFEntityExtractor):
    with pytest.raises(ValueError):
        extractor.train([], "/tmp/nonexistent")


def test_train_json2crf_empty(monkeypatch, tmp_path, extractor: CRFEntityExtractor):
    # Patch json2crf to return empty
    monkeypatch.setattr(extractor, "json2crf", lambda x: [])
    with pytest.raises(ValueError):
        extractor.train([{"spacy_doc": None}], str(tmp_path))


def test_train_success(monkeypatch, tmp_path, extractor: CRFEntityExtractor):
    # Create a fake spacy doc and training data
    tokens = [FakeToken("John", "NNP", 0, 0, 4), FakeToken("Doe", "NNP", 1, 5, 8)]
    doc = FakeDoc(tokens)
    training_data = [{"spacy_doc": doc, "entities": []}]

    # Ensure Trainer.train writes a file (DummyTrainer does)
    extractor.train(training_data, str(tmp_path))

    model_file = tmp_path / MODEL_NAME
    metadata_file = tmp_path / MODEL_METADATA_NAME
    assert model_file.exists()
    assert metadata_file.exists()
    # metadata should contain version and training_samples
    meta = json.loads(metadata_file.read_text())
    assert "version" in meta and meta["training_samples"] >= 0


def test_load_missing_model_returns_false(tmp_path, extractor: CRFEntityExtractor):
    assert extractor.load(str(tmp_path)) is False


def test_load_success(monkeypatch, tmp_path, extractor: CRFEntityExtractor):
    # Create dummy model file and metadata
    model_file = tmp_path / MODEL_NAME
    model_file.write_text("model")
    meta = {"version": "abcd1234"}
    metadata_path = tmp_path / MODEL_METADATA_NAME
    metadata_path.write_text(json.dumps(meta))

    # Patch Tagger to DummyTagger explicitly
    monkeypatch.setattr(module.pycrfsuite, "Tagger", lambda: DummyTagger())
    # Now load
    assert extractor.load(str(tmp_path)) is True


def test_crf2json_and_extract_labels():
    extractor = CRFEntityExtractor()
    # Tagged: B-PER then I-PER then O then B-LOC
    tagged = [("John", "B-PER"), ("Doe", "I-PER"), ("is", "O"), ("London", "B-LOC")]
    entities = extractor.crf2json(tagged)
    assert entities.get("PER") == "John Doe"
    assert entities.get("LOC") == "London"

    labels = extractor.extract_ner_labels([l for _, l in tagged])
    assert "PER" in labels and "LOC" in labels


def test_get_prediction_confidence_behavior():
    ext = CRFEntityExtractor()
    # No tagger -> 0.0
    assert ext._get_prediction_confidence("x", "B-PER") == 0.0

    # Marginal returns 0.8
    ext.tagger = DummyTagger(marginal_value=0.8)
    assert ext._get_prediction_confidence("x", "B-PER") == 0.8

    # Marginal raises -> returns threshold
    ext.tagger = DummyTagger(marginal_value=Exception("oops"))
    val = ext._get_prediction_confidence("x", "B-PER")
    assert val == ext.confidence_threshold


def test_cache_and_eviction(monkeypatch, extractor: CRFEntityExtractor):
    # Temporarily set small cache size
    monkeypatch.setattr(module, "ENTITY_CACHE_SIZE", 2)
    extractor._entity_cache = {"a": {"x": 1}, "b": {"y": 2}}
    extractor._cache_entities("c", {"z": 3})
    # one entry should have been evicted to maintain size
    assert len(extractor._entity_cache) == 2
    assert "c" in extractor._entity_cache


def test_predict_errors_and_cache(monkeypatch, extractor: CRFEntityExtractor):
    # Model not loaded -> error
    with pytest.raises(ValueError):
        extractor.predict({})

    # Set tagger and test missing spacy_doc
    extractor.tagger = DummyTagger(tag_return=["O"])
    with pytest.raises(ValueError):
        extractor.predict({"text": "hi"})

    # Test cached usage: prepare spacy doc
    tokens = [FakeToken("Alice", "NNP", 0, 0, 5), FakeToken("here", "RB", 1, 6, 10)]
    doc = FakeDoc(tokens)
    text_hash = hashlib.md5(doc.text.encode()).hexdigest()
    extractor._entity_cache = {text_hash: {"PER": "Alice"}}

    # If cached, tagger.tag should not be called; set tagger to raise if called
    extractor.tagger = DummyTagger(fail_tag=True)
    result = extractor.predict({"text": doc.text, "spacy_doc": doc})
    assert result == {"PER": "Alice"}


def test_predict_confidence_filtering(monkeypatch, extractor: CRFEntityExtractor):
    tokens = [FakeToken("Bob", "NNP", 0, 0, 3), FakeToken("lives", "VBZ", 1, 4, 9), FakeToken("NY", "NNP", 2, 10, 12)]
    doc = FakeDoc(tokens)
    # tagger.tag should return labels
    # Simulate B-PER, O, B-LOC
    extractor.tagger = DummyTagger(marginal_value=0.6, tag_return=["B-PER", "O", "B-LOC"])
    # Force marginal for LOC to be low by overriding marginal method
    def marginal(label, idx):
        if label.endswith("LOC"):
            return 0.1
        return 0.9
    extractor.tagger.marginal = marginal

    extractor.confidence_threshold = 0.5
    res = extractor.predict({"text": doc.text, "spacy_doc": doc})
    # PER should be present, LOC filtered out due low confidence
    assert "PER" in res and "LOC" not in res


def test_pos_tagger_and_json2crf_entities():
    tokens = [FakeToken("New", "NNP", 0, 0, 3), FakeToken("York", "NNP", 1, 4, 8), FakeToken("City", "NNP", 2, 9, 13)]
    doc = FakeDoc(tokens)
    ext = CRFEntityExtractor()
    tagged = ext.pos_tagger(doc)
    assert tagged[0][0] == "New" and tagged[0][1] == "NNP"

    # Build training example with an entity spanning "New York"
    training_example = {"spacy_doc": doc, "entities": [{"begin": 0, "end": 8, "name": "GPE"}]}
    crf = ext.json2crf([training_example])
    # Should produce 3 tokens labeled, with first two B-/I- tags
    assert len(crf) == 1
    labeled = crf[0]
    assert labeled[0][2] == "B-GPE"
    assert labeled[1][2] == "I-GPE"
    assert labeled[2][2] == "O"


def test_process_error_handling(monkeypatch):
    ext = CRFEntityExtractor()
    # missing text or spacy_doc -> returns unchanged
    msg = {"text": "", "spacy_doc": None}
    assert ext.process(msg) == msg

    # If predict raises, process should capture error
    ext.tagger = DummyTagger()
    def raise_predict(message):
        raise RuntimeError("boom")
    monkeypatch.setattr(ext, "predict", raise_predict)
    msg2 = {"text": "hi", "spacy_doc": FakeDoc([FakeToken("hi", "UH", 0, 0, 2)])}
    out = ext.process(msg2)
    assert out["entities"] == {}
    assert "extraction_error" in out


def test_validate_component_state(monkeypatch):
    ext = CRFEntityExtractor()
    # Simulate not loaded
    ext._is_loaded = False
    ok, err = ext.validate()
    assert not ok and "not loaded" in err.lower()

    ext._is_loaded = True
    ext.tagger = None
    ok2, err2 = ext.validate()
    assert not ok2 and "Tagger" in err2

    ext.tagger = DummyTagger()
    # _validate_model currently will succeed with DummyTagger
    ok3, err3 = ext.validate()
    assert ok3 is True