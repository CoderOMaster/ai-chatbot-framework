"""Scikit-learn based intent classifier for NLU pipeline.

This module provides a stateless intent classification component that loads
a pre-trained SVM model at startup and performs inference on incoming messages.
Training is delegated to a separate worker process.
"""

import os
from typing import Dict, Any, List, Tuple, Optional
import cloudpickle
import numpy as np
from app.bot.nlu.pipeline import NLUComponent
import logging

logger = logging.getLogger(__name__)


class SklearnIntentClassifier(NLUComponent):
    """Sklearn-based intent classifier implementing NLUComponent interface.
    
    This classifier loads a pre-trained SVM model and performs inference
    on incoming messages. The model is loaded once at startup and remains
    stateless across requests.
    
    Attributes:
        INTENT_RANKING_LENGTH: Number of top intents to return in ranking.
        MODEL_NAME: Filename for the serialized model artifact.
        model: Loaded scikit-learn classifier instance (SVC).
    """

    INTENT_RANKING_LENGTH: int = 3
    MODEL_NAME: str = "sklearn_intent_model.hd5"

    def __init__(self) -> None:
        """Initialize the intent classifier with no model loaded."""
        self.model: Optional[Any] = None

    def _get_spacy_embedding(self, spacy_doc: Any) -> np.ndarray:
        """Extract vector embedding from spaCy document.
        
        Args:
            spacy_doc: A spaCy Doc object with vector representation.
            
        Returns:
            NumPy array containing the document's vector embedding.
        """
        return np.array(spacy_doc.vector)

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train intent classifier using GridSearchCV on provided training data.
        
        This method performs hyperparameter tuning using GridSearchCV with SVM
        and saves the best estimator to disk. This method is typically called
        by a dedicated training worker, not in the request-serving path.
        
        Args:
            training_data: List of training examples, each containing:
                - "text": Input text string
                - "spacy_doc": Processed spaCy Doc object
                - "intent": Target intent label
            model_path: Directory path where the trained model will be saved.
            
        Raises:
            ValueError: If training data is empty or invalid.
            IOError: If model cannot be written to model_path.
        """
        from sklearn.model_selection import GridSearchCV
        from sklearn.svm import SVC

        # Extract features and labels from training data
        X: List[Any] = []
        y: List[str] = []
        for example in training_data:
            if example.get("text", "").strip() == "":
                continue
            X.append(example.get("spacy_doc"))
            y.append(example.get("intent"))

        if not X or not y:
            raise ValueError("Training data is empty after filtering")

        # Convert spaCy documents to embedding vectors
        X = np.stack([self._get_spacy_embedding(example) for example in X])

        # Determine cross-validation splits based on class distribution
        _, counts = np.unique(y, return_counts=True)
        cv_splits = max(2, min(5, np.min(counts) // 5))

        # Define hyperparameter grid for tuning
        tuned_parameters = [
            {"C": [1, 2, 5, 10, 20, 100], "gamma": [0.1], "kernel": ["linear"]}
        ]

        # Perform grid search with cross-validation
        classifier = GridSearchCV(
            SVC(C=1, probability=True, class_weight="balanced"),
            param_grid=tuned_parameters,
            n_jobs=-1,
            cv=cv_splits,
            scoring="f1_weighted",
            verbose=1,
        )

        classifier.fit(X, y)

        # Save the best model to disk
        if model_path:
            path = os.path.join(model_path, self.MODEL_NAME)
            with open(path, "wb") as f:
                cloudpickle.dump(classifier.best_estimator_, f)
            logger.info(f"Training completed & model written to {path}")

        self.model = classifier.best_estimator_

    def load(self, model_path: str) -> bool:
        """Load trained model from disk.
        
        This method is called at startup to load the pre-trained model
        for inference. The model remains in memory for the lifetime of
        the service instance.
        
        Args:
            model_path: Directory path containing the saved model artifact.
            
        Returns:
            True if model loaded successfully, False if file not found.
        """
        try:
            path = os.path.join(model_path, self.MODEL_NAME)
            with open(path, "rb") as f:
                self.model = cloudpickle.load(f)
            logger.info(f"Model loaded from {path}")
            return True
        except IOError as e:
            logger.error(f"Failed to load model from {path}: {e}")
            return False

    def _predict_proba(self, message: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
        """Predict intent probabilities for a message.
        
        Args:
            message: Message dictionary containing "spacy_doc" key.
            
        Returns:
            Tuple of (sorted_indices, sorted_probabilities) where:
            - sorted_indices: Indices of intents sorted by probability (descending)
            - sorted_probabilities: Corresponding probabilities (descending)
        """
        pred_result = self.model.predict_proba(
            [self._get_spacy_embedding(message.get("spacy_doc"))]
        )
        # Sort probabilities in descending order
        sorted_indices = np.fliplr(np.argsort(pred_result, axis=1))
        return sorted_indices, pred_result[:, sorted_indices]

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and extract intent information.
        
        Performs inference on the input message using the loaded model
        and enriches the message with predicted intent and confidence scores.
        
        Args:
            message: Input message dictionary with keys:
                - "text": Input text string
                - "spacy_doc": Processed spaCy Doc object
                
        Returns:
            Enriched message dictionary with added keys:
            - "intent": Dict with "intent" (str) and "confidence" (float)
            - "intent_ranking": List of top-N intent predictions with scores
        """
        if not message.get("text") or not message.get("spacy_doc"):
            message["intent"] = {"name": None, "confidence": 0.0}
            message["intent_ranking"] = []
            return message

        intent: Dict[str, Any] = {"name": None, "confidence": 0.0}
        intent_ranking: List[Dict[str, Any]] = []

        if self.model:
            intents, probabilities = self._predict_proba(message)
            intents = np.array(
                [self.model.classes_[intent] for intent in intents.flatten()]
            )
            probabilities = probabilities.flatten()

            if len(intents) > 0 and len(probabilities) > 0:
                ranking = list(zip(list(intents), list(probabilities)))
                ranking = ranking[: self.INTENT_RANKING_LENGTH]

                intent = {"intent": intents[0], "confidence": float(probabilities[0])}
                intent_ranking = [
                    {"intent": str(intent_name), "confidence": float(score)}
                    for intent_name, score in ranking
                ]
            else:
                intent = {"name": None, "confidence": 0.0}
                intent_ranking = []

        message["intent"] = intent
        message["intent_ranking"] = intent_ranking
        return message