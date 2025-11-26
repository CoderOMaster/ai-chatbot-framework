import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pycrfsuite

from app.bot.nlu.pipeline import (
    NLUComponent,
    ModelPath,
    ModelStorage,
    MessageDict,
    TrainingData,
)

MODEL_NAME = "crf_entity_extractor.model"
logger = logging.getLogger(__name__)


class CRFEntityExtractor(NLUComponent):
    """
    CRF based entity extractor.

    This component separates training and inference responsibilities. The
    train() and load() APIs accept a ModelPath (either a filesystem path or a
    ModelStorage implementation) and never assume the process working
    directory. When a storage backend is provided, training will write the
    model to a temporary file and then persist the bytes via the storage
    abstraction. Similarly, loading will download bytes from storage to a
    temporary file before opening the CRF tagger.
    """

    def __init__(self) -> None:
        self.tagger: Optional[pycrfsuite.Tagger] = None

    def extract_features(self, sent: List[Any], i: int) -> List[str]:
        """Extract token features for position i in sent."""
        word = sent[i][0]
        postag = sent[i][1]
        features = [
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
            word1 = sent[i - 1][0]
            postag1 = sent[i - 1][1]
            features.extend(
                [
                    "-1:word.lower=" + word1.lower(),
                    "-1:word.istitle=%s" % word1.istitle(),
                    "-1:word.isupper=%s" % word1.isupper(),
                    "-1:postag=" + postag1,
                    "-1:postag[:2]=" + postag1[:2],
                ]
            )
        else:
            features.append("BOS")

        if i < len(sent) - 1:
            word1 = sent[i + 1][0]
            postag1 = sent[i + 1][1]
            features.extend(
                [
                    "+1:word.lower=" + word1.lower(),
                    "+1:word.istitle=%s" % word1.istitle(),
                    "+1:word.isupper=%s" % word1.isupper(),
                    "+1:postag=" + postag1,
                    "+1:postag[:2]=" + postag1[:2],
                ]
            )
        else:
            features.append("EOS")

        return features

    def sent_to_features(self, sent: List[Any]) -> List[List[str]]:
        """Convert a tokenized sentence to a list of feature lists."""
        return [self.extract_features(sent, i) for i in range(len(sent))]

    def sent_to_labels(self, sent: List[Any]) -> List[str]:
        """Extract BIO labels from a tokenized, labeled sentence."""
        return [label for token, postag, label in sent]

    def train(self, training_data: TrainingData, model_path: ModelPath) -> None:
        """
        Train a CRF model from training_data and persist it to model_path.

        model_path may be either a filesystem directory (str / os.PathLike) or
        an object implementing the ModelStorage protocol. When given a
        ModelStorage implementation, the model is first trained to a temporary
        file and then the resulting bytes are saved via ModelStorage.save_bytes.
        """
        # Convert training data to CRF format
        ner_training_data = self.json2crf(training_data)

        features = [self.sent_to_features(s) for s in ner_training_data]
        labels = [self.sent_to_labels(s) for s in ner_training_data]

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

        # Filesystem path: ensure directory and train directly to file
        if isinstance(model_path, (str, os.PathLike)):
            model_path_str = str(model_path)
            output_path = os.path.join(model_path_str, MODEL_NAME)
            parent = os.path.dirname(output_path)
            if parent:
                Path(parent).mkdir(parents=True, exist_ok=True)
            trainer.train(output_path)
            logger.info("CRF model trained and saved to %s", output_path)
            return

        # ModelStorage: train to a temporary file then save bytes via storage
        storage: ModelStorage = model_path  # type: ignore
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
        try:
            trainer.train(tmp_path)
            with open(tmp_path, "rb") as f:
                data = f.read()
            storage.save_bytes(MODEL_NAME, data)
            logger.info("CRF model trained and saved to ModelStorage as %s", MODEL_NAME)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def load(self, model_path: ModelPath) -> bool:
        """
        Load CRF model from a filesystem path or ModelStorage. Returns True on
        success, False otherwise.
        """
        try:
            self.tagger = pycrfsuite.Tagger()

            if isinstance(model_path, (str, os.PathLike)):
                path = os.path.join(str(model_path), MODEL_NAME)
                self.tagger.open(path)
                logger.info("Loaded CRF model from %s", path)
                return True

            storage: ModelStorage = model_path  # type: ignore
            data = storage.load_bytes(MODEL_NAME)
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            try:
                self.tagger.open(tmp_path)
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            logger.info("Loaded CRF model from ModelStorage (%s)", MODEL_NAME)
            return True
        except Exception as e:
            logger.error("Error loading CRF model: %s", e)
            self.tagger = None
            return False

    def crf2json(self, tagged_sentence: Any) -> Dict[str, str]:
        """Convert a tagged sentence (word, BIO) into a dict of label->value."""
        labeled: Dict[str, str] = {}
        labels = set()
        for s, tp in tagged_sentence:
            if tp != "O":
                label = tp[2:]
                if tp.startswith("B"):
                    labeled[label] = s
                    labels.add(label)
                elif tp.startswith("I") and (label in labels):
                    labeled[label] += " %s" % s
        return labeled

    def extract_ner_labels(self, predicted_labels: List[str]) -> List[str]:
        """Return the entity type names present in predicted_labels."""
        labels: List[str] = []
        for tp in predicted_labels:
            if tp != "O":
                labels.append(tp[2:])
        return labels

    def predict(self, message: MessageDict) -> Dict[str, str]:
        """Run inference on a message. Requires load() to have been called.

        Returns a mapping of label -> extracted text.
        """
        if not self.tagger:
            raise RuntimeError("CRF tagger is not loaded. Call load() before predict().")

        spacy_doc = message.get("spacy_doc")
        if not spacy_doc:
            return {}

        tagged_token = self.pos_tagger(spacy_doc)
        words = [token.text for token in spacy_doc]
        predicted_labels = self.tagger.tag(self.sent_to_features(tagged_token))
        return self.crf2json(zip(words, predicted_labels))

    def pos_tagger(self, spacy_doc: Any) -> List[List[str]]:
        """Return a list of (text, tag) pairs for tokens in a spacy doc."""
        tagged_sentence: List[List[str]] = []
        for token in spacy_doc:
            tagged_sentence.append((token.text, token.tag_))
        return tagged_sentence

    def pos_tag_and_label(self, spacy_doc: Any) -> List[List[str]]:
        """Return token/tag pairs with a default BIO label 'O'."""
        tagged_sentence = self.pos_tagger(spacy_doc)
        tagged_sentence_json: List[List[str]] = []
        for token, postag in tagged_sentence:
            tagged_sentence_json.append([token, postag, "O"])
        return tagged_sentence_json

    def json2crf(self, training_data: TrainingData) -> List[List[List[str]]]:
        """
        Convert training examples with spacy docs and entity annotations into
        CRFSuite training format: a list of sentences, each sentence being a
        list of [token, postag, BIO] entries.
        """
        labeled_examples: List[List[List[str]]] = []

        for example in training_data:
            spacy_doc = example.get("spacy_doc")
            if not spacy_doc:
                continue

            tagged_example = self.pos_tag_and_label(spacy_doc)

            for entity in example.get("entities", []):
                begin_char = entity.get("begin")
                end_char = entity.get("end")
                entity_name = entity.get("name")

                span = spacy_doc.char_span(begin_char, end_char)
                if not span:
                    continue
                for i, token in enumerate(span):
                    token_index = token.i
                    if 0 <= token_index < len(tagged_example):
                        if i == 0:
                            bio = f"B-{entity_name}"
                        else:
                            bio = f"I-{entity_name}"
                        tagged_example[token_index][2] = bio

            labeled_examples.append(tagged_example)
        return labeled_examples

    def process(self, message: MessageDict) -> MessageDict:
        """Process a message and attach extracted entities if possible."""
        if not message.get("text") or not message.get("spacy_doc"):
            return message

        try:
            entities = self.predict(message)
        except RuntimeError:
            # Model not loaded; do not perform inference in online path
            logger.debug("CRF model not loaded; skipping NER prediction.")
            return message

        message["entities"] = entities
        return message