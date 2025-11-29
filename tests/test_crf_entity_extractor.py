from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List
from unittest.mock import MagicMock

import pytest

from app.bot.nlu.entity_extractors.crf_entity_extractor import CRFEntityExtractor
from app.config import AppConfig


class FakeToken:
    def __init__(
        self,
        text: str,
        start_char: int,
        end_char: int,
        tag: str,
        index: int,
    ) -> None:
        self.text = text
        self.start_char = start_char
        self.end_char = end_char
        self.tag_ = tag
        self.i = index


class FakeDoc:
    def __init__(self, tokens: List[FakeToken]) -> None:
        self.tokens = tokens

    def __iter__(self) -> Iterable[FakeToken]:
        return iter(self.tokens)

    def char_span(self, begin: int, end: int) -> List[FakeToken] | None:
        span = [token for token in self.tokens if begin <= token.start_char and token.end_char <= end]
        return span or None


def make_fake_doc(words: List[str], tags: List[str] | None = None) -> FakeDoc:
    tokens: List[FakeToken] = []
    current_pos = 0
    for index, word in enumerate(words):
        tag = tags[index] if tags else "NN"
        start = current_pos
        end = start + len(word)
        tokens.append(FakeToken(word, start, end, tag, index))
        current_pos = end + 1
    return FakeDoc(tokens)


@pytest.fixture
def extractor() -> CRFEntityExtractor:
    return CRFEntityExtractor()


def test_default_model_storage_uses_app_config(monkeypatch, tmp_path: Path) -> None:
    models_dir = tmp_path / "shared_models"
    mock_config = MagicMock()
    mock_config.MODELS_DIR = str(models_dir)
    monkeypatch.setattr("app.bot.nlu.entity_extractors.crf_entity_extractor.app_config", mock_config)
    expected = models_dir.expanduser().resolve(strict=False) / "crf"
    assert CRFEntityExtractor.default_model_storage() == expected


def test_resolve_model_directory_returns_absolute_path() -> None:
    relative = Path("relative/path/to/model")
    resolved = CRFEntityExtractor._resolve_model_directory(relative)
    assert resolved == relative.expanduser().resolve(strict=False)
    assert resolved.is_absolute()


def test_model_file_path_appends_filename(tmp_path: Path) -> None:
    model_dir = tmp_path / "models"
    result = CRFEntityExtractor._model_file_path(model_dir)
    assert result.parent == model_dir
    assert result.name == CRFEntityExtractor.MODEL_FILENAME


def test_extract_features_includes_contextual_markers() -> None:
    sentence = [("New", "NNP", "B-LOC"), ("York", "NNP", "I-LOC"), ("City", "NNP", "O")]
    extractor = CRFEntityExtractor()
    first = extractor.extract_features(sentence, 0)
    middle = extractor.extract_features(sentence, 1)
    last = extractor.extract_features(sentence, 2)

    assert "BOS" in first
    assert "EOS" not in first
    assert any(item.startswith("+1:word.lower=york") for item in first)
    assert any(item.startswith("-1:word.lower=new") for item in middle)
    assert "EOS" in last
    assert "+1:word.lower=" not in last


def test_sent_to_features_and_labels() -> None:
    sentence = [("Hello", "NNP", "B-GREETING"), ("World", "NN", "I-GREETING")]
    extractor = CRFEntityExtractor()
    feature_vectors = extractor.sent_to_features(sentence)
    labels = extractor.sent_to_labels(sentence)

    assert len(feature_vectors) == len(sentence)
    assert labels == ["B-GREETING", "I-GREETING"]


def test_train_invokes_pycrfsuite_trainer(monkeypatch, tmp_path: Path) -> None:
    instance_holder: Dict[str, Any] = {}

    class DummyTrainer:
        def __init__(self, verbose: bool = False) -> None:
            instance_holder["instance"] = self
            self.verbose = verbose
            self.append_calls: List[Any] = []
            self.params: Dict[str, Any] | None = None
            self.trained_path: str | None = None

        def append(self, xseq: Any, yseq: Any) -> None:
            self.append_calls.append((xseq, yseq))

        def set_params(self, params: Dict[str, Any]) -> None:
            self.params = params

        def train(self, path: str) -> None:
            self.trained_path = path

    monkeypatch.setattr(
        "app.bot.nlu.entity_extractors.crf_entity_extractor.pycrfsuite.Trainer",
        DummyTrainer,
    )

    doc = make_fake_doc(["Hello", "World"], ["NNP", "NNP"])
    training_data = [
        {
            "spacy_doc": doc,
            "entities": [{"begin": 0, "end": 11, "name": "GREETING"}],
        }
    ]
    model_dir = tmp_path / "crf_models"
    extractor = CRFEntityExtractor()
    extractor.train(training_data, model_dir)

    trainer = instance_holder.get("instance")
    assert trainer is not None
    assert trainer.params == {
        "c1": 1.0,
        "c2": 1e-3,
        "max_iterations": 50,
        "feature.possible_transitions": True,
    }
    assert len(trainer.append_calls) == 1
    expected_path = str(
        CRFEntityExtractor._model_file_path(
            CRFEntityExtractor._resolve_model_directory(model_dir)
        )
    )
    assert trainer.trained_path == expected_path
    assert (CRFEntityExtractor._resolve_model_directory(model_dir)).exists()


def test_load_returns_false_when_model_missing(tmp_path: Path) -> None:
    extractor = CRFEntityExtractor()
    assert not extractor.load(tmp_path / "missing")


def test_load_success_opens_model_and_records_directory(monkeypatch, tmp_path: Path) -> None:
    model_dir = tmp_path / "crf_dir"
    model_dir.mkdir(parents=True)
    model_file = model_dir / CRFEntityExtractor.MODEL_FILENAME
    model_file.write_text("binary")

    opened: Dict[str, Any] = {}

    class DummyTagger:
        def __init__(self) -> None:
            opened["instance"] = self
            self.opened_path: str | None = None

        def open(self, path: str) -> None:
            self.opened_path = path

    monkeypatch.setattr(
        "app.bot.nlu.entity_extractors.crf_entity_extractor.pycrfsuite.Tagger",
        DummyTagger,
    )

    extractor = CRFEntityExtractor()
    result = extractor.load(model_dir)

    assert result is True
    assert extractor.tagger is opened.get("instance")
    assert extractor._model_directory == CRFEntityExtractor._resolve_model_directory(model_dir)
    assert extractor.tagger.opened_path == str(model_file)


def test_load_handles_exceptions_and_returns_false(monkeypatch, tmp_path: Path) -> None:
    model_dir = tmp_path / "crf_dir"
    model_dir.mkdir(parents=True)
    (model_dir / CRFEntityExtractor.MODEL_FILENAME).write_text("binary")

    class FaultyTagger:
        def open(self, path: str) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "app.bot.nlu.entity_extractors.crf_entity_extractor.pycrfsuite.Tagger",
        FaultyTagger,
    )

    extractor = CRFEntityExtractor()
    assert extractor.load(model_dir) is False


def test_crf2json_compiles_entities() -> None:
    extractor = CRFEntityExtractor()
    tagged = [("Rasa", "B-ORG"), ("OSS", "I-ORG"), ("is", "O")]
    result = extractor.crf2json(tagged)
    assert result == {"ORG": "Rasa OSS"}


def test_extract_ner_labels_filters_out_O() -> None:
    extractor = CRFEntityExtractor()
    tags = ["B-PER", "I-PER", "O", "B-ORG"]
    assert extractor.extract_ner_labels(tags) == ["PER", "PER", "ORG"]


def test_predict_without_tagger_returns_empty() -> None:
    extractor = CRFEntityExtractor()
    assert extractor.predict({"spacy_doc": make_fake_doc(["Hello"], ["NNP"])}) == {}


def test_predict_without_spacy_doc_returns_empty() -> None:
    extractor = CRFEntityExtractor()

    class DummyTagger:
        def tag(self, features: List[List[str]]) -> List[str]:  # pragma: no cover - stub
            return ["O"]

    extractor.tagger = DummyTagger()
    assert extractor.predict({"text": "Hello"}) == {}


def test_predict_success_returns_detected_entities() -> None:
    extractor = CRFEntityExtractor()

    class DummyTagger:
        def __init__(self) -> None:
            self.received_features: List[List[str]] | None = None

        def tag(self, features: List[List[str]]) -> List[str]:
            self.received_features = features
            return ["B-ORG", "O"]

    extractor.tagger = DummyTagger()
    doc = make_fake_doc(["Rasa", "NLP"], ["NNP", "NNP"])
    result = extractor.predict({"spacy_doc": doc})
    assert result == {"ORG": "Rasa"}


def test_pos_tagger_returns_token_pairs() -> None:
    extractor = CRFEntityExtractor()
    doc = make_fake_doc(["Testing", "Pandas"], ["VB", "NN"])
    assert extractor.pos_tagger(doc) == [(token.text, token.tag_) for token in doc]


def test_pos_tag_and_label_initializes_bio() -> None:
    extractor = CRFEntityExtractor()
    doc = make_fake_doc(["Hello", "World"], ["UH", "NN"])
    expected = [[token.text, token.tag_, "O"] for token in doc]
    assert extractor.pos_tag_and_label(doc) == expected


def test_json2crf_returns_empty_when_no_doc() -> None:
    extractor = CRFEntityExtractor()
    assert extractor.json2crf([{ "entities": [] }]) == []


def test_json2crf_builds_labels_for_entities() -> None:
    extractor = CRFEntityExtractor()
    doc = make_fake_doc(["Rasa", "Lab"], ["NNP", "NNP"])
    labeled = extractor.json2crf([
        {
            "spacy_doc": doc,
            "entities": [{"begin": 0, "end": doc.tokens[-1].end_char, "name": "ORG"}],
        }
    ])

    assert labeled
    assert labeled[0][0][2] == "B-ORG"
    assert labeled[0][1][2] == "I-ORG"


def test_json2crf_skips_invalid_entity_annotations() -> None:
    extractor = CRFEntityExtractor()
    doc = make_fake_doc(["Skip", "This"], ["NNP", "NNP"])
    invalid_entities = [
        {"begin": None, "end": 5, "name": "ORG"},
        {"begin": 0, "end": 4, "name": ""},
        {"begin": 100, "end": 110, "name": "ORG"},
    ]
    labeled = extractor.json2crf([{"spacy_doc": doc, "entities": invalid_entities}])
    assert labeled
    assert labeled[0][0][2] == "O"
    assert labeled[0][1][2] == "O"


def test_process_ignores_missing_annotations() -> None:
    extractor = CRFEntityExtractor()
    message = {"text": "hello"}
    assert extractor.process(message) == message


def test_process_attaches_entities_when_predict_returns_values() -> None:
    extractor = CRFEntityExtractor()
    extractor.predict = lambda message: {"LOC": "Earth"}
    message = {"text": "Hello", "spacy_doc": make_fake_doc(["Hello"], ["NNP"])}
    updated = extractor.process(message)
    assert updated["entities"] == {"LOC": "Earth"}
    assert updated is message


__all__ = ["FakeDoc", "FakeToken"]