"""CRF-based Named Entity Recognition component for NLU pipeline.

This module provides a Conditional Random Field (CRF) based entity extractor
that performs NER training, prediction, and model import/export operations.
Requires pycrfsuite with native compilation support.
"""

import pycrfsuite
import logging
import os
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from shared.nlu.pipeline import NLUComponent

MODEL_NAME = "crf_entity_extractor.model"
MODEL_METADATA_NAME = "crf_metadata.json"
logger = logging.getLogger(__name__)


class CRFEntityExtractor(NLUComponent):
    """Performs NER training, prediction, model import/export using CRF.
    
    This component uses Conditional Random Fields (CRF) to perform Named Entity
    Recognition tasks. It supports model versioning and comprehensive error handling.
    """

    def __init__(self) -> None:
        """Initialize the CRF entity extractor."""
        self.tagger: Optional[pycrfsuite.Tagger] = None
        self.model_version: Optional[str] = None

    def extract_features(self, sent: List[tuple], i: int) -> List[str]:
        """Extract features for a given token in a sentence.
        
        Args:
            sent: List of (word, postag) tuples representing a sentence.
            i: Index of the token to extract features for.
            
        Returns:
            List of feature strings for the token.
            
        Raises:
            IndexError: If index i is out of bounds.
            ValueError: If token format is invalid.
        """
        if i < 0 or i >= len(sent):
            raise IndexError(f"Token index {i} out of bounds for sentence of length {len(sent)}")
        
        try:
            word = sent[i][0]
            postag = sent[i][1]
        except (TypeError, IndexError) as e:
            raise ValueError(f"Invalid token format at index {i}: {sent[i]}") from e

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

    def sent_to_features(self, sent: List[tuple]) -> List[List[str]]:
        """Extract features from a sentence.
        
        Args:
            sent: List of (word, postag) tuples representing a sentence.
            
        Returns:
            List of feature lists, one per token.
        """
        return [self.extract_features(sent, i) for i in range(len(sent))]

    def sent_to_labels(self, sent: List[tuple]) -> List[str]:
        """Extract labels from a sentence.
        
        Args:
            sent: List of (token, postag, label) tuples.
            
        Returns:
            List of labels.
        """
        return [label for token, postag, label in sent]

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train the CRF component with given training data and save to model_path.
        
        Args:
            training_data: List of training examples with annotated entities.
            model_path: Directory path where the trained model should be saved.
            
        Raises:
            ValueError: If training data is empty or invalid.
            IOError: If model cannot be saved to the specified path.
        """
        if not training_data:
            raise ValueError("Training data cannot be empty")

        try:
            # Convert training data to CRF format
            ner_training_data = self.json2crf(training_data)
            
            if not ner_training_data:
                raise ValueError("No valid training examples after conversion to CRF format")

            # Train using existing logic
            features = [self.sent_to_features(s) for s in ner_training_data]
            labels = [self.sent_to_labels(s) for s in ner_training_data]

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
            
            # Ensure model directory exists
            os.makedirs(model_path, exist_ok=True)
            
            path = os.path.join(model_path, MODEL_NAME)
            trainer.train(path)
            
            # Save model metadata with version info
            self.model_version = datetime.utcnow().isoformat()
            metadata = {
                "version": self.model_version,
                "model_name": MODEL_NAME,
                "training_examples": len(ner_training_data),
            }
            metadata_path = os.path.join(model_path, MODEL_METADATA_NAME)
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
            
            logger.info(f"CRF model trained successfully. Version: {self.model_version}")
        except Exception as e:
            logger.error(f"Error training CRF model: {e}")
            raise

    def load(self, model_path: str) -> bool:
        """Load the CRF model from the given path.
        
        Args:
            model_path: Path to the model directory.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            path = os.path.join(model_path, MODEL_NAME)
            if not os.path.exists(path):
                logger.error(f"Model file not found at {path}")
                return False
            
            self.tagger = pycrfsuite.Tagger()
            self.tagger.open(path)
            
            # Load model metadata if available
            metadata_path = os.path.join(model_path, MODEL_METADATA_NAME)
            if os.path.exists(metadata_path):
                try:
                    with open(metadata_path, "r") as f:
                        metadata = json.load(f)
                        self.model_version = metadata.get("version")
                        logger.info(f"Loaded CRF model version: {self.model_version}")
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"Could not load model metadata: {e}")
            
            logger.info(f"CRF model loaded successfully from {path}")
            return True
        except Exception as e:
            logger.error(f"Error loading CRF model: {e}")
            return False

    def crf2json(self, tagged_sentence: List[tuple]) -> Dict[str, str]:
        """Extract label-value pairs from NER prediction output.
        
        Args:
            tagged_sentence: List of (word, label) tuples from CRF prediction.
            
        Returns:
            Dictionary mapping entity types to extracted values.
        """
        labeled = {}
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
        """Extract unique entity type names from NER predictions.
        
        Args:
            predicted_labels: List of BIO-tagged labels from CRF.
            
        Returns:
            List of unique entity type names (without BIO prefix).
        """
        labels = []
        for tp in predicted_labels:
            if tp != "O":
                labels.append(tp[2:])
        return labels

    def predict(self, message: Dict[str, Any]) -> Dict[str, str]:
        """Predict NER labels for given message.
        
        Args:
            message: Message dictionary with 'spacy_doc' key.
            
        Returns:
            Dictionary of extracted entities.
            
        Raises:
            RuntimeError: If model is not loaded or message is invalid.
        """
        if self.tagger is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        
        try:
            spacy_doc = message.get("spacy_doc")
            if not spacy_doc:
                raise ValueError("Message must contain 'spacy_doc' key")
            
            tagged_token = self.pos_tagger(spacy_doc)
            words = [token.text for token in spacy_doc]
            predicted_labels = self.tagger.tag(self.sent_to_features(tagged_token))
            return self.crf2json(zip(words, predicted_labels))
        except Exception as e:
            logger.error(f"Error during prediction: {e}")
            raise

    def pos_tagger(self, spacy_doc: Any) -> List[tuple]:
        """Perform POS tagging on a given spacy document.
        
        Args:
            spacy_doc: Spacy Doc object to tag.
            
        Returns:
            List of (word, postag) tuples.
        """
        tagged_sentence = []
        for token in spacy_doc:
            tagged_sentence.append((token.text, token.tag_))
        return tagged_sentence

    def pos_tag_and_label(self, spacy_doc: Any) -> List[List[str]]:
        """Perform POS tagging and initialize BIO labeling on given sentence.
        
        Args:
            spacy_doc: Spacy Doc object to process.
            
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
        
        Takes JSON annotated data and converts it to CRFSuite training data
        representation with BIO tagging.
        
        Args:
            training_data: List of training examples with annotated entities.
                          Each example should have 'spacy_doc' and 'entities' keys.
            
        Returns:
            List of tokenized, POS-tagged, and BIO-labeled sentences.
            
        Raises:
            ValueError: If training data format is invalid.
        """
        labeled_examples = []

        for example_idx, example in enumerate(training_data):
            try:
                spacy_doc = example.get("spacy_doc")
                if not spacy_doc:
                    logger.warning(f"Example {example_idx}: Missing or empty spacy_doc, skipping")
                    continue

                # Initialize tokens with POS tagging and default BIO label as 'O'
                tagged_example = self.pos_tag_and_label(spacy_doc)

                # Process entities in the example
                entities = example.get("entities", [])
                if not isinstance(entities, list):
                    logger.warning(f"Example {example_idx}: Entities is not a list, skipping")
                    continue

                for entity_idx, entity in enumerate(entities):
                    try:
                        begin_char = entity.get("begin")
                        end_char = entity.get("end")
                        entity_name = entity.get("name")

                        if begin_char is None or end_char is None or not entity_name:
                            logger.warning(
                                f"Example {example_idx}, Entity {entity_idx}: "
                                f"Missing required fields (begin, end, name), skipping"
                            )
                            continue

                        # Use char_span to map entity character offsets to token spans
                        span = spacy_doc.char_span(begin_char, end_char)
                        if not span:
                            logger.debug(
                                f"Example {example_idx}, Entity {entity_idx}: "
                                f"Could not resolve span [{begin_char}:{end_char}], skipping"
                            )
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
                            else:
                                logger.warning(
                                    f"Example {example_idx}, Entity {entity_idx}: "
                                    f"Token index {token_index} out of bounds"
                                )
                    except Exception as e:
                        logger.warning(
                            f"Example {example_idx}, Entity {entity_idx}: "
                            f"Error processing entity: {e}"
                        )
                        continue

                # Append the fully labeled example
                labeled_examples.append(tagged_example)
            except Exception as e:
                logger.warning(f"Example {example_idx}: Error processing example: {e}")
                continue

        if not labeled_examples:
            logger.warning("No valid training examples after json2crf conversion")

        return labeled_examples

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and return the extracted information.
        
        Args:
            message: Input message dictionary with 'text' and 'spacy_doc' keys.
            
        Returns:
            Message dictionary with 'entities' key added.
        """
        if not message.get("text") or not message.get("spacy_doc"):
            logger.debug("Message missing required fields (text, spacy_doc)")
            return message

        try:
            entities = self.predict(message)
            message["entities"] = entities
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            message["entities"] = {}

        return message