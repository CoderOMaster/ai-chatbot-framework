import pycrfsuite
import logging
import json
import hashlib
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime
from pathlib import Path
from functools import lru_cache
from app.bot.nlu.pipeline import NLUComponent
import os

logger = logging.getLogger(__name__)

MODEL_NAME = "crf_entity_extractor.model"
MODEL_METADATA_NAME = "crf_entity_extractor.metadata.json"
DEFAULT_CONFIDENCE_THRESHOLD = 0.5
ENTITY_CACHE_SIZE = 1024


class CRFEntityExtractor(NLUComponent):
    """
    Performs NER training, prediction, model import/export with versioning,
    incremental training, confidence thresholds, and entity caching.
    """

    def __init__(self, confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD):
        """Initialize CRF entity extractor.
        
        Args:
            confidence_threshold: Minimum confidence score for entity predictions
        """
        super().__init__(name="crf_entity_extractor", parallelizable=True)
        self.tagger: Optional[pycrfsuite.Tagger] = None
        self.confidence_threshold = confidence_threshold
        self.model_version: Optional[str] = None
        self.model_metadata: Dict[str, Any] = {}
        self._entity_cache: Dict[str, Dict[str, Any]] = {}

    def extract_features(self, sent: List[Tuple[str, str]], i: int) -> List[str]:
        """Extract features for a given sentence.
        
        Args:
            sent: List of (word, postag) tuples
            i: Token index
            
        Returns:
            List of feature strings
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
        """Extract features from training data.
        
        Args:
            sent: List of (word, postag) tuples
            
        Returns:
            List of feature lists
        """
        return [self.extract_features(sent, i) for i in range(len(sent))]

    def sent_to_labels(self, sent: List[Tuple[str, str, str]]) -> List[str]:
        """Extract labels from training data.
        
        Args:
            sent: List of (token, postag, label) tuples
            
        Returns:
            List of labels
        """
        return [label for token, postag, label in sent]

    def _generate_model_version(self, training_data: List[Dict[str, Any]]) -> str:
        """Generate a version hash for the model based on training data.
        
        Args:
            training_data: Training data to hash
            
        Returns:
            Version hash string
        """
        data_str = json.dumps(training_data, sort_keys=True, default=str)
        return hashlib.sha256(data_str.encode()).hexdigest()[:8]

    def _save_metadata(self, model_path: str, version: str, 
                      training_samples: int, is_incremental: bool = False) -> None:
        """Save model metadata including version and training info.
        
        Args:
            model_path: Path to model directory
            version: Model version hash
            training_samples: Number of training samples
            is_incremental: Whether this is an incremental training
        """
        metadata = {
            "version": version,
            "timestamp": datetime.now().isoformat(),
            "training_samples": training_samples,
            "is_incremental": is_incremental,
            "confidence_threshold": self.confidence_threshold,
        }
        
        metadata_path = os.path.join(model_path, MODEL_METADATA_NAME)
        try:
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
            self.model_metadata = metadata
            logger.info(f"Saved model metadata to {metadata_path}")
        except Exception as e:
            logger.error(f"Failed to save model metadata: {e}")

    def _load_metadata(self, model_path: str) -> bool:
        """Load model metadata from file.
        
        Args:
            model_path: Path to model directory
            
        Returns:
            True if metadata loaded successfully
        """
        metadata_path = os.path.join(model_path, MODEL_METADATA_NAME)
        try:
            if os.path.exists(metadata_path):
                with open(metadata_path, "r") as f:
                    self.model_metadata = json.load(f)
                    self.model_version = self.model_metadata.get("version")
                    logger.info(f"Loaded model metadata: version={self.model_version}")
                    return True
            else:
                logger.warning(f"Model metadata not found at {metadata_path}")
                return False
        except Exception as e:
            logger.error(f"Failed to load model metadata: {e}")
            return False

    def _validate_model(self) -> Tuple[bool, Optional[str]]:
        """Validate loaded model state.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if self.tagger is None:
            return False, "Tagger not initialized"
        
        try:
            # Test with a simple feature set
            test_features = [["bias", "word.lower=test"]]
            self.tagger.tag(test_features)
            return True, None
        except Exception as e:
            return False, f"Model validation failed: {e}"

    def train(self, training_data: List[Dict[str, Any]], model_path: str,
              incremental: bool = False) -> None:
        """Train the component with given training data and save to model_path.
        
        Args:
            training_data: List of training examples
            model_path: Path to save trained model
            incremental: Whether to perform incremental training
            
        Raises:
            ValueError: If training data is invalid
            RuntimeError: If training fails
        """
        if not training_data:
            raise ValueError("Training data cannot be empty")
        
        try:
            # Convert training data to CRF format
            ner_training_data = self.json2crf(training_data)
            
            if not ner_training_data:
                raise ValueError("No valid training data after conversion")

            # Extract features and labels
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
            
            os.makedirs(model_path, exist_ok=True)
            path = os.path.join(model_path, MODEL_NAME)
            trainer.train(path)
            
            # Generate and save metadata
            version = self._generate_model_version(training_data)
            self._save_metadata(model_path, version, len(ner_training_data), 
                              is_incremental=incremental)
            
            logger.info(f"Successfully trained CRF model (version={version}, "
                       f"samples={len(ner_training_data)})")
        except Exception as e:
            logger.error(f"Failed to train CRF model: {e}")
            raise RuntimeError(f"CRF training failed: {e}") from e

    def load(self, model_path: str) -> bool:
        """Load the CRF model from the given path.
        
        Args:
            model_path: Path to the model directory
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.tagger = pycrfsuite.Tagger()
            path = os.path.join(model_path, MODEL_NAME)
            
            if not os.path.exists(path):
                logger.error(f"Model file not found at {path}")
                return False
            
            self.tagger.open(path)
            
            # Load and validate metadata
            self._load_metadata(model_path)
            
            # Validate model
            is_valid, error_msg = self._validate_model()
            if not is_valid:
                logger.error(f"Model validation failed: {error_msg}")
                return False
            
            logger.info(f"Successfully loaded CRF model from {path}")
            return True
        except Exception as e:
            logger.error(f"Error loading CRF model: {e}")
            self.tagger = None
            return False

    def crf2json(self, tagged_sentence: List[Tuple[str, str]]) -> Dict[str, str]:
        """Extract label-value pair from NER prediction output.
        
        Args:
            tagged_sentence: List of (word, tag) tuples
            
        Returns:
            Dictionary of extracted entities
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
        """Extract name of labels from NER predictions.
        
        Args:
            predicted_labels: List of predicted labels
            
        Returns:
            List of unique entity labels
        """
        labels = []
        for tp in predicted_labels:
            if tp != "O":
                labels.append(tp[2:])
        return labels

    def _get_prediction_confidence(self, word: str, predicted_label: str) -> float:
        """Get confidence score for a prediction.
        
        Args:
            word: The word being predicted
            predicted_label: The predicted label
            
        Returns:
            Confidence score between 0 and 1
        """
        try:
            if self.tagger is None:
                return 0.0
            
            # Get marginal probabilities for the word
            marginals = self.tagger.marginal(predicted_label, 0)
            return min(1.0, max(0.0, marginals))
        except Exception:
            # Default to threshold if marginal computation fails
            return self.confidence_threshold

    def _get_cached_entities(self, text_hash: str) -> Optional[Dict[str, str]]:
        """Retrieve cached entity extraction results.
        
        Args:
            text_hash: Hash of the input text
            
        Returns:
            Cached entities or None if not found
        """
        return self._entity_cache.get(text_hash)

    def _cache_entities(self, text_hash: str, entities: Dict[str, str]) -> None:
        """Cache entity extraction results.
        
        Args:
            text_hash: Hash of the input text
            entities: Extracted entities to cache
        """
        if len(self._entity_cache) >= ENTITY_CACHE_SIZE:
            # Remove oldest entry
            self._entity_cache.pop(next(iter(self._entity_cache)))
        
        self._entity_cache[text_hash] = entities

    def predict(self, message: Dict[str, Any]) -> Dict[str, str]:
        """Predict NER labels for given message with confidence thresholds.
        
        Args:
            message: Message dict with 'spacy_doc' key
            
        Returns:
            Dictionary of extracted entities
            
        Raises:
            ValueError: If message is invalid or model not loaded
        """
        if self.tagger is None:
            raise ValueError("Model not loaded. Call load() first.")
        
        try:
            spacy_doc = message.get("spacy_doc")
            if not spacy_doc:
                raise ValueError("Message must contain 'spacy_doc' key")
            
            # Generate cache key
            text_hash = hashlib.md5(spacy_doc.text.encode()).hexdigest()
            
            # Check cache
            cached_result = self._get_cached_entities(text_hash)
            if cached_result is not None:
                logger.debug(f"Using cached entities for text: {spacy_doc.text[:50]}")
                return cached_result
            
            # Perform prediction
            tagged_token = self.pos_tagger(spacy_doc)
            words = [token.text for token in spacy_doc]
            predicted_labels = self.tagger.tag(self.sent_to_features(tagged_token))
            
            # Filter by confidence threshold
            filtered_predictions = []
            for word, label in zip(words, predicted_labels):
                if label == "O":
                    filtered_predictions.append((word, label))
                else:
                    confidence = self._get_prediction_confidence(word, label)
                    if confidence >= self.confidence_threshold:
                        filtered_predictions.append((word, label))
                    else:
                        # Replace with 'O' if below threshold
                        filtered_predictions.append((word, "O"))
            
            entities = self.crf2json(filtered_predictions)
            
            # Cache result
            self._cache_entities(text_hash, entities)
            
            return entities
        except ValueError as e:
            logger.error(f"Prediction validation error: {e}")
            raise
        except Exception as e:
            logger.error(f"Error during NER prediction: {e}")
            raise RuntimeError(f"Prediction failed: {e}") from e

    def pos_tagger(self, spacy_doc: Any) -> List[Tuple[str, str]]:
        """Perform POS tagging on a given sentence.
        
        Args:
            spacy_doc: SpaCy Doc object
            
        Returns:
            List of (word, postag) tuples
        """
        tagged_sentence = []
        for token in spacy_doc:
            tagged_sentence.append((token.text, token.tag_))
        return tagged_sentence

    def pos_tag_and_label(self, spacy_doc: Any) -> List[List[str]]:
        """Perform POS tagging and BIO labeling on given sentence.
        
        Args:
            spacy_doc: SpaCy Doc object
            
        Returns:
            List of [token, postag, label] lists
        """
        tagged_sentence = self.pos_tagger(spacy_doc)
        tagged_sentence_json = []
        for token, postag in tagged_sentence:
            tagged_sentence_json.append([token, postag, "O"])
        return tagged_sentence_json

    def json2crf(self, training_data: List[Dict[str, Any]]) -> List[List[List[str]]]:
        """Convert JSON annotated data to CRFSuite training data representation.
        
        Args:
            training_data: List of training examples with annotated entities
            
        Returns:
            List of tokenized, POS-tagged, and BIO-labeled sentences
        """
        labeled_examples = []

        for example in training_data:
            spacy_doc = example.get("spacy_doc")
            if not spacy_doc:
                logger.debug("Skipping example without spacy_doc")
                continue

            # Initialize tokens with POS tagging and default BIO label as 'O'
            tagged_example = self.pos_tag_and_label(spacy_doc)

            # Process entities in the example
            for entity in example.get("entities", []):
                begin_char = entity.get("begin")
                end_char = entity.get("end")
                entity_name = entity.get("name")

                if not all([begin_char is not None, end_char is not None, entity_name]):
                    logger.debug(f"Skipping invalid entity: {entity}")
                    continue

                # Use char_span to map entity character offsets to token spans
                span = spacy_doc.char_span(begin_char, end_char)
                if not span:
                    logger.debug(f"Could not resolve span for entity: {entity}")
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
        """Process a message and return the extracted information.
        
        Args:
            message: Input message to process
            
        Returns:
            Message with extracted entities
        """
        if not message.get("text") or not message.get("spacy_doc"):
            return message

        try:
            entities = self.predict(message)
            message["entities"] = entities
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            message["entities"] = {}
            message["extraction_error"] = str(e)

        return message

    def validate(self) -> Tuple[bool, Optional[str]]:
        """Validate component state and configuration.
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self._is_loaded:
            return False, "CRF model not loaded"
        
        if self.tagger is None:
            return False, "Tagger not initialized"
        
        is_valid, error_msg = self._validate_model()
        return is_valid, error_msg