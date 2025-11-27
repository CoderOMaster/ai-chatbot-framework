import logging
import os
import json
import hashlib
from typing import Dict, Any, List, Iterable, Optional, Protocol, Iterator
from app.bot.nlu.pipeline import NLUComponent

MODEL_NAME = "crf_entity_extractor.model"
META_NAME = "crf_entity_extractor_meta.json"
MODULE_VERSION = "1.0"
logger = logging.getLogger(__name__)


class CRFBackend(Protocol):
    """Protocol describing the minimal backend API the extractor expects.

    This allows swapping out pycrfsuite for a different implementation during
    testing or alternative runtimes.
    """

    def new_trainer(self, verbose: bool = False):
        ...

    def trainer_append(self, trainer: Any, xseq: List[List[str]], yseq: List[str]) -> None:
        ...

    def trainer_set_params(self, trainer: Any, params: Dict[str, Any]) -> None:
        ...

    def trainer_train(self, trainer: Any, path: str) -> None:
        ...

    def new_tagger(self) -> Any:
        ...

    def tagger_open(self, tagger: Any, path: str) -> None:
        ...

    def tagger_tag(self, tagger: Any, features: List[List[str]]) -> List[str]:
        ...


class PyCRFSuiteBackend:
    """Adapter around pycrfsuite to satisfy CRFBackend protocol.

    Importing pycrfsuite is performed lazily so environments that provide a
    different backend can replace this adapter without importing the module at
    import-time of this file.
    """

    def __init__(self):
        try:
            import pycrfsuite  # imported lazily
        except Exception as e:  # pragma: no cover - environment dependent
            logger.exception("pycrfsuite not available: %s", e)
            raise
        self._py = pycrfsuite

    def new_trainer(self, verbose: bool = False):
        return self._py.Trainer(verbose=verbose)

    def trainer_append(self, trainer: Any, xseq: List[List[str]], yseq: List[str]) -> None:
        trainer.append(xseq, yseq)

    def trainer_set_params(self, trainer: Any, params: Dict[str, Any]) -> None:
        trainer.set_params(params)

    def trainer_train(self, trainer: Any, path: str) -> None:
        trainer.train(path)

    def new_tagger(self) -> Any:
        return self._py.Tagger()

    def tagger_open(self, tagger: Any, path: str) -> None:
        tagger.open(path)

    def tagger_tag(self, tagger: Any, features: List[List[str]]) -> List[str]:
        return tagger.tag(features)


class CRFEntityExtractor(NLUComponent):
    """Performs NER training, prediction and model import/export.

    The CRF backend can be injected for testing or alternate runtimes via the
    `backend` parameter. Training supports streaming input (any iterable of
    example dicts) and writes model metadata including a corpus hash for
    reproducibility.
    """

    def __init__(self, backend: Optional[CRFBackend] = None) -> None:
        self.tagger: Optional[Any] = None
        self._backend = backend or PyCRFSuiteBackend()
        self.metadata: Dict[str, Any] = {}

    def extract_features(self, sent: List[Any], i: int) -> List[str]:
        """Extract features for token i in sentence.

        Args:
            sent: Sequence of token tuples (token, pos, label).
            i: index of token in sent.
        """
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
        """Extract features for whole sentence."""
        return [self.extract_features(sent, i) for i in range(len(sent))]

    def sent_to_labels(self, sent: List[Any]) -> List[str]:
        """Extract labels from a labeled sentence."""
        return [label for token, postag, label in sent]

    def train(self, training_data: Iterable[Dict[str, Any]], model_path: str) -> None:
        """Train the component with streaming training data and save to model_path.

        training_data: Any iterable yielding examples (dicts) that contain a
        'spacy_doc' and optional 'entities' list. This can be a generator to
        avoid loading all data into memory.
        """
        os.makedirs(model_path, exist_ok=True)

        trainer = self._backend.new_trainer(verbose=False)

        # Stream examples: convert to CRF format sentence by sentence and append
        num_sents = 0
        num_tokens = 0
        hasher = hashlib.sha256()

        for example in training_data:
            ner_sentences = self.json2crf([example])
            for s in ner_sentences:
                features = self.sent_to_features(s)
                labels = self.sent_to_labels(s)
                self._backend.trainer_append(trainer, features, labels)

                # Update corpus hash and counters
                for token, postag, label in s:
                    line = f"{token}|{postag}|{label}\n"
                    hasher.update(line.encode("utf-8"))
                    num_tokens += 1
                num_sents += 1

        # Trainer params
        self._backend.trainer_set_params(
            trainer,
            {
                "c1": 1.0,
                "c2": 1e-3,
                "max_iterations": 50,
                "feature.possible_transitions": True,
            },
        )

        model_file = os.path.join(model_path, MODEL_NAME)
        self._backend.trainer_train(trainer, model_file)

        # Persist metadata
        self.metadata = {
            "version": MODULE_VERSION,
            "training_hash": hasher.hexdigest(),
            "num_sentences": num_sents,
            "num_tokens": num_tokens,
        }
        meta_file = os.path.join(model_path, META_NAME)
        try:
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception("Failed to write CRF metadata to %s", meta_file)

    def load(self, model_path: str) -> bool:
        """Load the CRF model and metadata from the given path."""
        try:
            self.tagger = self._backend.new_tagger()
            model_file = os.path.join(model_path, MODEL_NAME)
            self._backend.tagger_open(self.tagger, model_file)

            # load metadata if present
            meta_file = os.path.join(model_path, META_NAME)
            if os.path.exists(meta_file):
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        self.metadata = json.load(f)
                except Exception:
                    logger.exception("Failed to read CRF metadata from %s", meta_file)

            return True
        except Exception as e:
            logger.error("Error loading CRF model: %s", e)
            return False

    def crf2json(self, tagged_sentence: Iterable[Any]) -> Dict[str, str]:
        """Convert CRF BIO tags to a dict of label -> text."""
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

    def extract_ner_labels(self, predicted_labels: Iterable[str]) -> List[str]:
        """Return list of entity names from predicted BIO labels."""
        labels: List[str] = []
        for tp in predicted_labels:
            if tp != "O":
                labels.append(tp[2:])
        return labels

    def predict(self, message: Dict[str, Any]) -> Dict[str, str]:
        """Predict NER labels for given message and return dict of entities."""
        spacy_doc = message.get("spacy_doc")
        tagged_token = self.pos_tagger(spacy_doc)
        words = [token.text for token in spacy_doc]
        if not self.tagger:
            raise RuntimeError("CRF tagger is not loaded. Call load() before predict().")
        predicted_labels = self._backend.tagger_tag(self.tagger, self.sent_to_features(tagged_token))
        return self.crf2json(zip(words, predicted_labels))

    def pos_tagger(self, spacy_doc: Any) -> List[List[str]]:
        """Return list of (text, tag) pairs for spacy tokens."""
        tagged_sentence: List[List[str]] = []
        for token in spacy_doc:
            tagged_sentence.append([token.text, token.tag_])
        return tagged_sentence

    def pos_tag_and_label(self, spacy_doc: Any) -> List[List[Any]]:
        """Return POS tagged tokens with default 'O' BIO labels."""
        tagged_sentence = self.pos_tagger(spacy_doc)
        tagged_sentence_json: List[List[Any]] = []
        for token, postag in tagged_sentence:
            tagged_sentence_json.append([token, postag, "O"])
        return tagged_sentence_json

    def json2crf(self, training_data: Iterable[Dict[str, Any]]) -> List[List[Any]]:
        """Convert annotated examples into CRF training sentences.

        Accepts an iterable of examples but will process the provided iterable in
        full for the caller. For streaming use in train() callers may directly
        pass the generator and training will not accumulate all sentences in
        memory at once.
        """
        labeled_examples: List[List[Any]] = []

        for example in training_data:
            spacy_doc = example.get("spacy_doc")
            if not spacy_doc:
                continue

            tagged_example = self.pos_tag_and_label(spacy_doc)

            for entity in example.get("entities", []) or []:
                begin_char = entity.get("begin")
                end_char = entity.get("end")
                entity_name = entity.get("name")

                span = spacy_doc.char_span(begin_char, end_char)
                if not span:
                    continue
                for i, token in enumerate(span):
                    token_index = token.i
                    if 0 <= token_index < len(tagged_example):
                        bio = f"B-{entity_name}" if i == 0 else f"I-{entity_name}"
                        tagged_example[token_index][2] = bio

            labeled_examples.append(tagged_example)
        return labeled_examples

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and return the extracted information."""
        if not message.get("text") or not message.get("spacy_doc"):
            return message

        entities = self.predict(message)
        message["entities"] = entities
        return message