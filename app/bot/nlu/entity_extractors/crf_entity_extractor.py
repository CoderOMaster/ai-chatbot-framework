"""CRF-based Named Entity Recognition component for NLU pipeline.

This module provides a Conditional Random Field (CRF) based entity extractor
that implements the NLUComponent interface. It supports training, model loading,
and entity extraction from text.

The component uses pycrfsuite for efficient CRF training and inference,
with model artifacts stored in the configured MODELS_DIR.
"""

import pycrfsuite
import logging
import os
from typing import Dict, Any, List, Tuple

from app.bot.nlu.pipeline import NLUComponent
from app.config import app_config

MODEL_NAME = "crf_entity_extractor.model"
logger = logging.getLogger(__name__)


class CRFEntityExtractor(NLUComponent):
    """Conditional Random Field based Named Entity Recognition extractor.
    
    Performs NER training, prediction, model import/export using CRFSuite.
    Model artifacts are stored in app_config.MODELS_DIR.
    
    Attributes:
        tagger: Loaded pycrfsuite.Tagger instance for inference.
    """

    def __init__(self) -> None:
        """Initialize the CRF entity extractor."""
        self.tagger: pycrfsuite.Tagger | None = None

    def extract_features(self, sent: List[Tuple[str, str]], i: int) -> List[str]:
        """Extract features for a given token in a sentence.
        
        Generates contextual features including word properties, POS tags,
        and neighboring token information for CRF training/inference.
        
        Args:
            sent: List of (word, postag) tuples representing a sentence.
            i: Index of the token to extract features for.
            
        Returns:
            List of feature strings for the token.
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

    def sent_to_features(self, sent: List[Tuple[str, str]]) -> List[List[str]]:
        """Extract features from all tokens in a sentence.
        
        Args:
            sent: List of (word, postag) tuples representing a sentence.
            
        Returns:
            List of feature lists, one per token.
        """
        return [self.extract_features(sent, i) for i in range(len(sent))]

    def sent_to_labels(self, sent: List[Tuple[str, str, str]]) -> List[str]:
        """Extract BIO labels from a sentence.
        
        Args:
            sent: List of (token, postag, label) tuples representing a sentence.
            
        Returns:
            List of BIO labels.
        """
        return [label for token, postag, label in sent]

    def train(self, training_data: List[Dict[str, Any]], model_path: str | None = None) -> None:
        """Train the CRF model with given training data.
        
        Converts training data to CRF format, trains the model, and saves
        artifacts to the configured MODELS_DIR (or specified model_path).
        
        This method should be called from a background worker to avoid
        blocking request processing.
        
        Args:
            training_data: List of training examples with annotated entities.
            model_path: Optional override for model directory. Defaults to app_config.MODELS_DIR.
            
        Raises:
            ValueError: If training data is empty or malformed.
            OSError: If model directory cannot be created or written to.
        """
        if not training_data:
            raise ValueError("Training data cannot be empty")
        
        # Use configured MODELS_DIR if no override provided
        if model_path is None:
            model_path = app_config.MODELS_DIR
        
        # Ensure model directory exists
        os.makedirs(model_path, exist_ok=True)
        
        # Convert training data to CRF format
        ner_training_data = self.json2crf(training_data)
        
        if not ner_training_data:
            raise ValueError("No valid training examples after conversion")

        # Extract features and labels
        features = [self.sent_to_features(s) for s in ner_training_data]
        labels = [self.sent_to_labels(s) for s in ner_training_data]

        # Train CRF model
        trainer = pycrfsuite.Trainer(verbose=False)
        for xseq, yseq in zip(features, labels):
            trainer.append(xseq, yseq)

        trainer.set_params(
            {
                "c1": 1.0,  # coefficient for L1 penalty
                "c2": 1e-3,  # coefficient for L2 penalty
                "max_iterations": 50,  # stop earlier
                # include transitions that are possible, but not observed
                "feature.possible_transitions": True,
            }
        )
        
        # Save trained model
        model_file_path = os.path.join(model_path, MODEL_NAME)
        trainer.train(model_file_path)
        logger.info(f"CRF model trained and saved to {model_file_path}")

    def load(self, model_path: str | None = None) -> bool:
        """Load the CRF model from disk.
        
        Loads a previously trained model from the configured MODELS_DIR
        (or specified model_path) for inference.
        
        Args:
            model_path: Optional override for model directory. Defaults to app_config.MODELS_DIR.
            
        Returns:
            True if loading succeeded, False otherwise.
        """
        try:
            # Use configured MODELS_DIR if no override provided
            if model_path is None:
                model_path = app_config.MODELS_DIR
            
            self.tagger = pycrfsuite.Tagger()
            model_file_path = os.path.join(model_path, MODEL_NAME)
            self.tagger.open(model_file_path)
            logger.info(f"CRF model loaded from {model_file_path}")
            return True
        except Exception as e:
            logger.error(f"Error loading CRF model: {e}")
            return False

    def crf2json(self, tagged_sentence: List[Tuple[str, str]]) -> Dict[str, str]:
        """Convert CRF predictions to entity dictionary.
        
        Extracts label-value pairs from NER prediction output using BIO tagging.
        
        Args:
            tagged_sentence: List of (word, tag) tuples from CRF prediction.
            
        Returns:
            Dictionary mapping entity labels to extracted values.
        """
        labeled: Dict[str, str] = {}
        labels: set = set()
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
        """Extract unique entity label names from predictions.
        
        Args:
            predicted_labels: List of BIO tags from CRF prediction.
            
        Returns:
            List of unique entity label names (without BIO prefix).
        """
        labels = []
        for tp in predicted_labels:
            if tp != "O":
                labels.append(tp[2:])
        return labels

    def predict(self, message: Dict[str, Any]) -> Dict[str, str]:
        """Predict NER labels for a message.
        
        Args:
            message: Message dictionary containing 'spacy_doc' key.
            
        Returns:
            Dictionary of extracted entities.
            
        Raises:
            RuntimeError: If model is not loaded.
        """
        if self.tagger is None:
            raise RuntimeError("CRF model not loaded. Call load() first.")
        
        spacy_doc = message.get("spacy_doc")
        tagged_token = self.pos_tagger(spacy_doc)
        words = [token.text for token in spacy_doc]
        predicted_labels = self.tagger.tag(self.sent_to_features(tagged_token))
        return self.crf2json(zip(words, predicted_labels))

    def pos_tagger(self, spacy_doc: Any) -> List[Tuple[str, str]]:
        """Perform POS tagging on a spaCy document.
        
        Args:
            spacy_doc: Processed spaCy Doc object.
            
        Returns:
            List of (word, postag) tuples.
        """
        tagged_sentence = []
        for token in spacy_doc:
            tagged_sentence.append((token.text, token.tag_))
        return tagged_sentence

    def pos_tag_and_label(self, spacy_doc: Any) -> List[List[str]]:
        """Perform POS tagging and initialize BIO labels.
        
        Args:
            spacy_doc: Processed spaCy Doc object.
            
        Returns:
            List of [token, postag, label] lists with default 'O' labels.
        """
        tagged_sentence = self.pos_tagger(spacy_doc)
        tagged_sentence_json = []
        for token, postag in tagged_sentence:
            tagged_sentence_json.append([token, postag, "O"])
        return tagged_sentence_json

    def json2crf(self, training_data: List[Dict[str, Any]]) -> List[List[List[str]]]:
        """Convert JSON annotated data to CRFSuite training format.
        
        Transforms training examples with entity annotations into tokenized,
        POS-tagged, and BIO-labeled sentences suitable for CRF training.
        
        Args:
            training_data: List of training examples with 'spacy_doc' and 'entities' keys.
            
        Returns:
            List of labeled sentences in CRF format: [[[token, postag, bio_label], ...], ...]
        """
        labeled_examples = []

        for example in training_data:
            spacy_doc = example.get("spacy_doc")
            if not spacy_doc:
                continue  # Skip if spacy_doc is None or empty

            # Initialize tokens with POS tagging and default BIO label as 'O'
            tagged_example = self.pos_tag_and_label(spacy_doc)

            # Process entities in the example
            for entity in example.get("entities", []):
                begin_char = entity.get("begin")
                end_char = entity.get("end")
                entity_name = entity.get("name")

                # Use char_span to map entity character offsets to token spans
                span = spacy_doc.char_span(begin_char, end_char)
                if not span:
                    # Skip if the span cannot be resolved (e.g., partial tokens)
                    continue
                # BIO tagging for the resolved token span
                for i, token in enumerate(span):
                    token_index = token.i
                    if 0 <= token_index < len(tagged_example):
                        if i == 0:
                            bio = f"B-{entity_name}"
                        else:
                            bio = f"I-{entity_name}"
                        tagged_example[token_index][2] = bio

            # Append the fully labeled example
            labeled_examples.append(tagged_example)
        return labeled_examples

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and extract entities.
        
        Inference method that extracts named entities from a message
        using the loaded CRF model.
        
        Args:
            message: Input message dictionary with 'text' and 'spacy_doc' keys.
            
        Returns:
            Message dictionary with 'entities' key added.
        """
        if not message.get("text") or not message.get("spacy_doc"):
            return message

        entities = self.predict(message)
        message["entities"] = entities
        return message