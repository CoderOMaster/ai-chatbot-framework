from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import pycrfsuite
from app.config import app_config
from app.bot.nlu.pipeline import NLUComponent

TOKEN_TRIPLE = Tuple[str, str, str]
POS_TAGGED_TOKEN = Tuple[str, str]

MODEL_FILE_NAME = "crf_entity_extractor.model"
MODEL_STORAGE_SUBDIRECTORY = "crf"
logger = logging.getLogger(__name__)


class CRFEntityExtractor(NLUComponent):
    """CRF-based NER component that supports offline training and online inference."""

    MODEL_DIRECTORY_NAME = MODEL_STORAGE_SUBDIRECTORY
    MODEL_FILENAME = MODEL_FILE_NAME

    def __init__(self) -> None:
        self.tagger: pycrfsuite.Tagger | None = None
        self._model_directory: Path | None = None

    @classmethod
    def default_model_storage(cls) -> Path:
        """Return the shared filesystem location for CRF artifacts."""
        return (
            Path(app_config.MODELS_DIR)
            .expanduser()
            .resolve(strict=False)
            / cls.MODEL_DIRECTORY_NAME
        )

    @staticmethod
    def _resolve_model_directory(model_path: Path | str) -> Path:
        """Normalize the provided model storage path without assuming the current working directory."""
        return Path(model_path).expanduser().resolve(strict=False)

    @classmethod
    def _model_file_path(cls, model_dir: Path) -> Path:
        """Return the absolute path of the CRF model file inside the provided directory."""
        return model_dir / cls.MODEL_FILENAME

    def extract_features(self, sent: Sequence[TOKEN_TRIPLE], i: int) -> List[str]:
        """Create a feature list for a token in a tagged sentence."""
        word, postag = sent[i][0], sent[i][1]
        features: List[str] = [
            "bias",
            "word.lower=" + word.lower(),
            "word[-3:]=" + word[-3:],
            "word[-2:]=" + word[-2:],
            "word.isupper=%s" % word.isupper(),
            "word.istitle=%s" % word.istitle(),
            "word.isdigit=%s" % word.isdigit(),
            "postag=" + postag,
            "postag[:2]=" + postag[:2],
        ]

        if i > 0:
            prev_word, prev_tag = sent[i - 1][0], sent[i - 1][1]
            features.extend(
                [
                    "-1:word.lower=" + prev_word.lower(),
                    "-1:word.istitle=%s" % prev_word.istitle(),
                    "-1:word.isupper=%s" % prev_word.isupper(),
                    "-1:postag=" + prev_tag,
                    "-1:postag[:2]=" + prev_tag[:2],
                ]
            )
        else:
            features.append("BOS")

        if i < len(sent) - 1:
            next_word, next_tag = sent[i + 1][0], sent[i + 1][1]
            features.extend(
                [
                    "+1:word.lower=" + next_word.lower(),
                    "+1:word.istitle=%s" % next_word.istitle(),
                    "+1:word.isupper=%s" % next_word.isupper(),
                    "+1:postag=" + next_tag,
                    "+1:postag[:2]=" + next_tag[:2],
                ]
            )
        else:
            features.append("EOS")

        return features

    def sent_to_features(self, sent: Sequence[TOKEN_TRIPLE]) -> List[List[str]]:
        """Convert a sentence into a list of token feature vectors."""
        return [self.extract_features(sent, i) for i in range(len(sent))]

    def sent_to_labels(self, sent: Sequence[TOKEN_TRIPLE]) -> List[str]:
        """Extract BIO labels from a tokenized sentence."""
        return [label for _, _, label in sent]

    def train(self, training_data: Sequence[Dict[str, Any]], model_path: Path | str) -> None:
        """Offline training entry point for background workers.

        The worker should provide an explicit storage location such as
        `app_config.MODELS_DIR / MODEL_DIRECTORY_NAME`.
        """
        ner_training_data = self.json2crf(training_data)
        if not ner_training_data:
            return

        features = [self.sent_to_features(example) for example in ner_training_data]
        labels = [self.sent_to_labels(example) for example in ner_training_data]

        trainer = pycrfsuite.Trainer(verbose=False)
        for xseq, yseq in zip(features, labels):
            trainer.append(xseq, yseq)

        trainer.set_params(
            {
                "c1": 1.0,
                "c2": 1e-3,
                "max_iterations": 50,
                "feature.possible_transitions": True,
            }
        )

        model_dir = self._resolve_model_directory(model_path)
        model_dir.mkdir(parents=True, exist_ok=True)
        trainer_path = self._model_file_path(model_dir)
        trainer.train(str(trainer_path))

    def load(self, model_path: Path | str) -> bool:
        """Load artifacts from the supplied CRF model directory for runtime inference."""
        try:
            model_dir = self._resolve_model_directory(model_path)
            model_file = self._model_file_path(model_dir)
            if not model_file.exists():
                logger.warning("CRF model not found at %s", model_file)
                return False

            self.tagger = pycrfsuite.Tagger()
            self.tagger.open(str(model_file))
            self._model_directory = model_dir
            return True
        except Exception as exc:  # pragma: no cover - pycrfsuite raises C-level errors
            logger.error("Error loading CRF model: %s", exc)
            return False

    def crf2json(self, tagged_sentence: Iterable[Tuple[str, str]]) -> Dict[str, str]:
        """Convert BIO predictions into a dictionary of entity names to values."""
        labeled: Dict[str, str] = {}
        labels: set[str] = set()
        for token, tag in tagged_sentence:
            if tag == "O":
                continue
            label = tag[2:]
            if tag.startswith("B"):
                labeled[label] = token
                labels.add(label)
            elif tag.startswith("I") and label in labels:
                labeled[label] += f" {token}"
        return labeled

    def extract_ner_labels(self, predicted_labels: Iterable[str]) -> List[str]:
        """Return the set of recognized entity labels from a prediction sequence."""
        return [tag[2:] for tag in predicted_labels if tag != "O"]

    def predict(self, message: Dict[str, Any]) -> Dict[str, str]:
        """Run the CRF model against a parsed Spacy document."""
        if not self.tagger:
            logger.warning("CRF tagger is not initialized; skipping prediction.")
            return {}

        spacy_doc = message.get("spacy_doc")
        if not spacy_doc:
            return {}

        tagged_token = self.pos_tagger(spacy_doc)
        words = [token.text for token in spacy_doc]
        predicted_labels = self.tagger.tag(self.sent_to_features(tagged_token))
        return self.crf2json(zip(words, predicted_labels))

    def pos_tagger(self, spacy_doc: Any) -> List[POS_TAGGED_TOKEN]:
        """Produce POS-tagged token tuples from a SpaCy document."""
        return [(token.text, token.tag_) for token in spacy_doc]

    def pos_tag_and_label(self, spacy_doc: Any) -> List[List[str]]:
        """Prepare a spaCy sentence with default BIO labels."""
        return [[token.text, token.tag_, "O"] for token in spacy_doc]

    def json2crf(self, training_data: Sequence[Dict[str, Any]]) -> List[List[str]]:
        """Translate JSON-style training annotations into BIO-labeled sentences."""
        labeled_examples: List[List[str]] = []

        for example in training_data:
            spacy_doc = example.get("spacy_doc")
            if not spacy_doc:
                continue

            tagged_example = self.pos_tag_and_label(spacy_doc)

            for entity in example.get("entities", []):
                begin_char = entity.get("begin")
                end_char = entity.get("end")
                entity_name = entity.get("name")

                if begin_char is None or end_char is None or not entity_name:
                    continue

                span = spacy_doc.char_span(begin_char, end_char)
                if not span:
                    continue

                for i, token in enumerate(span):
                    token_index = token.i
                    if not (0 <= token_index < len(tagged_example)):
                        continue
                    tag = "B-" + entity_name if i == 0 else "I-" + entity_name
                    tagged_example[token_index][2] = tag

            labeled_examples.append(tagged_example)
        return labeled_examples

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Mutate the incoming message with extracted entities."""
        if not message.get("text") or not message.get("spacy_doc"):
            return message

        entities = self.predict(message)
        message["entities"] = entities
        return message


__all__ = ["CRFEntityExtractor"]