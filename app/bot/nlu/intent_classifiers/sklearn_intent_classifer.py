import os
from typing import Dict, Any, List, Tuple, Optional
import cloudpickle
import numpy as np
from shared.nlu.pipeline import NLUComponent
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class SklearnIntentClassifier(NLUComponent):
    """Sklearn-based intent classifier that implements NLUComponent interface.
    
    Features:
    - Model versioning and metadata tracking
    - Confidence threshold filtering
    - Model caching strategy for warm starts
    - Robust error handling for model loading
    """

    INTENT_RANKING_LENGTH = 3
    MODEL_NAME = "sklearn_intent_model.hd5"
    MODEL_VERSION = "1.0"
    MIN_CONFIDENCE_THRESHOLD = 0.5
    CACHE_ENABLED = True

    def __init__(self, confidence_threshold: float = MIN_CONFIDENCE_THRESHOLD):
        """Initialize the intent classifier.
        
        Args:
            confidence_threshold: Minimum confidence score for predictions (0.0-1.0)
        """
        self.model = None
        self.model_metadata: Dict[str, Any] = {}
        self.confidence_threshold = confidence_threshold
        self._model_cache: Optional[Any] = None
        self._cache_timestamp: Optional[datetime] = None

    def get_spacy_embedding(self, spacy_doc) -> np.ndarray:
        """Extract spacy embedding vector from document.
        
        Args:
            spacy_doc: Spacy Doc object
            
        Returns:
            Embedding vector as numpy array
        """
        return np.array(spacy_doc.vector)

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train intent classifier for given training data.
        
        Args:
            training_data: List of training examples with text, spacy_doc, and intent
            model_path: Directory path to save the trained model
        """
        from sklearn.model_selection import GridSearchCV
        from sklearn.svm import SVC

        X = []
        y = []
        for example in training_data:
            if example.get("text", "").strip() == "":
                continue
            X.append(example.get("spacy_doc"))
            y.append(example.get("intent"))

        X = np.stack([self.get_spacy_embedding(example) for example in X])

        _, counts = np.unique(y, return_counts=True)
        cv_splits = max(2, min(5, np.min(counts) // 5))

        tuned_parameters = [
            {"C": [1, 2, 5, 10, 20, 100], "gamma": [0.1], "kernel": ["linear"]}
        ]

        classifier = GridSearchCV(
            SVC(C=1, probability=True, class_weight="balanced"),
            param_grid=tuned_parameters,
            n_jobs=-1,
            cv=cv_splits,
            scoring="f1_weighted",
            verbose=1,
        )

        classifier.fit(X, y)

        if model_path:
            path = os.path.join(model_path, self.MODEL_NAME)
            self._save_model(classifier.best_estimator_, path)
            logger.info(f"Training completed & model written out to {path}")

        self.model = classifier.best_estimator_
        self._update_model_metadata()
        self._invalidate_cache()

    def _save_model(self, model: Any, path: str) -> None:
        """Save model with metadata to disk.
        
        Args:
            model: Trained sklearn model
            path: File path to save model
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            cloudpickle.dump(model, f)

    def _update_model_metadata(self) -> None:
        """Update model metadata with version and timestamp."""
        self.model_metadata = {
            "version": self.MODEL_VERSION,
            "timestamp": datetime.utcnow().isoformat(),
            "confidence_threshold": self.confidence_threshold,
        }

    def _invalidate_cache(self) -> None:
        """Invalidate model cache."""
        self._model_cache = None
        self._cache_timestamp = None

    def load(self, model_path: str) -> bool:
        """Load trained model from given path.
        
        Args:
            model_path: Directory path containing the model file
            
        Returns:
            True if model loaded successfully, False otherwise
        """
        try:
            path = os.path.join(model_path, self.MODEL_NAME)
            if not os.path.exists(path):
                logger.error(f"Model file not found at {path}")
                return False
            
            with open(path, "rb") as f:
                self.model = cloudpickle.load(f)
            
            self._update_model_metadata()
            if self.CACHE_ENABLED:
                self._model_cache = self.model
                self._cache_timestamp = datetime.utcnow()
            
            logger.info(f"Model loaded successfully from {path}")
            return True
        except FileNotFoundError as e:
            logger.error(f"Model file not found: {e}")
            return False
        except (IOError, OSError) as e:
            logger.error(f"Error loading model from {model_path}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error loading model: {e}")
            return False

    def predict_proba(self, X: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
        """Predict intent probabilities for input text.
        
        Args:
            X: Input dictionary with spacy_doc key
            
        Returns:
            Tuple of (sorted intent indices, sorted probabilities)
        """
        if self.model is None:
            logger.warning("Model not loaded, cannot predict")
            return np.array([]), np.array([])

        pred_result = self.model.predict_proba(
            [self.get_spacy_embedding(X.get("spacy_doc"))]
        )
        # sort the probabilities retrieving the indices of the elements
        sorted_indices = np.fliplr(np.argsort(pred_result, axis=1))
        return sorted_indices, pred_result[:, sorted_indices]

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and return the extracted intent information.
        
        Args:
            message: Input message dictionary with text and spacy_doc
            
        Returns:
            Message dictionary with added intent and intent_ranking fields
        """
        if not message.get("text") or not message.get("spacy_doc"):
            message["intent"] = {"name": None, "confidence": 0.0}
            message["intent_ranking"] = []
            return message

        intent = {"name": None, "confidence": 0.0}
        intent_ranking = []

        if self.model:
            intents, probabilities = self.predict_proba(message)
            intents = [self.model.classes_[intent] for intent in intents.flatten()]
            probabilities = probabilities.flatten()

            if len(intents) > 0 and len(probabilities) > 0:
                ranking = list(zip(list(intents), list(probabilities)))
                ranking = ranking[: self.INTENT_RANKING_LENGTH]

                # Filter by confidence threshold
                if probabilities[0] >= self.confidence_threshold:
                    intent = {"intent": intents[0], "confidence": float(probabilities[0])}
                    intent_ranking = [
                        {"intent": intent_name, "confidence": float(score)}
                        for intent_name, score in ranking
                        if score >= self.confidence_threshold
                    ]
                else:
                    intent = {"name": None, "confidence": 0.0}
                    intent_ranking = []
            else:
                intent = {"name": None, "confidence": 0.0}
                intent_ranking = []

        message["intent"] = intent
        message["intent_ranking"] = intent_ranking
        return message