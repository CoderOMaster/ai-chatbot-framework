import os
from typing import Any, Dict, List, Optional, Tuple

import cloudpickle
import numpy as np
from pydantic_settings import BaseSettings
from sklearn.base import ClassifierMixin

from app.bot.nlu.pipeline import NLUComponent
import logging

logger = logging.getLogger(__name__)


class SklearnIntentClassifierConfig(BaseSettings):
    """Environment aware configuration for the sklearn intent classifier."""

    model_path: str = "/app/models"
    model_name: str = "sklearn_intent_model.hd5"


class SklearnIntentClassifier(NLUComponent):
    """Sklearn intent classifier used by dialogue-manager for inference."""

    INTENT_RANKING_LENGTH = 3

    def __init__(
        self,
        config: Optional[SklearnIntentClassifierConfig] = None,
        model: Optional[ClassifierMixin] = None,
    ) -> None:
        self.config = config or SklearnIntentClassifierConfig()
        self.model: Optional[ClassifierMixin] = model

    def _model_full_path(self, override_path: Optional[str] = None) -> str:
        root_path = override_path or self.config.model_path
        os.makedirs(root_path, exist_ok=True)
        return os.path.join(root_path, self.config.model_name)

    def get_spacy_embedding(self, spacy_doc: Any) -> np.ndarray:
        """Return the vector representation extracted from a spaCy doc."""
        return np.array(spacy_doc.vector)

    def train(
        self,
        training_data: List[Dict[str, Any]],
        output_path: Optional[str] = None,
    ) -> None:
        """Train and serialize a GridSearch-backed sklearn intent classifier."""
        from sklearn.model_selection import GridSearchCV
        from sklearn.svm import SVC

        X: List[Any] = []
        y: List[str] = []
        for example in training_data:
            if not example.get("text", "").strip():
                continue
            spacy_doc = example.get("spacy_doc")
            if spacy_doc is None:
                continue
            X.append(spacy_doc)
            y.append(example.get("intent", ""))

        if not X or not y:
            raise ValueError("Training data must contain at least one valid example.")

        embeddings = np.stack([self.get_spacy_embedding(example) for example in X])

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

        classifier.fit(embeddings, y)

        path = self._model_full_path(override_path=output_path)
        with open(path, "wb") as f:
            cloudpickle.dump(classifier.best_estimator_, f)
        logger.info("Training completed & model written out to %s", path)

        self.model = classifier.best_estimator_

    def load(self, model_path: Optional[str] = None) -> bool:
        """Load the classifier from the configured model path."""
        try:
            path = self._model_full_path(override_path=model_path)
            with open(path, "rb") as f:
                self.model = cloudpickle.load(f)
            return True
        except OSError as exc:
            logger.warning("Unable to load sklearn model from %s: %s", path, exc)
            return False

    def predict_proba(self, message: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
        """Predict probability distribution over classes for the provided message."""
        if not self.model:
            raise RuntimeError("Model is not loaded; call load() before prediction.")

        embedding = self.get_spacy_embedding(message.get("spacy_doc"))
        probabilities = self.model.predict_proba([embedding])
        sorted_indices = np.fliplr(np.argsort(probabilities, axis=1))
        return sorted_indices, probabilities[:, sorted_indices]

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Extract intent and intent ranking for a single message."""
        if not message.get("text") or not message.get("spacy_doc"):
            return message

        intent_data: Dict[str, Any] = {"name": None, "confidence": 0.0}
        intent_ranking: List[Dict[str, Any]] = []

        if self.model:
            intents, probabilities = self.predict_proba(message)
            flat_intents = [self.model.classes_[idx] for idx in intents.flatten()]
            flat_probs = probabilities.flatten()

            if flat_intents and flat_probs.size:
                ranking = list(zip(flat_intents, flat_probs))[: self.INTENT_RANKING_LENGTH]
                intent_data = {"intent": ranking[0][0], "confidence": ranking[0][1]}
                intent_ranking = [
                    {"intent": intent_name, "confidence": score}
                    for intent_name, score in ranking
                ]

        message["intent"] = intent_data
        message["intent_ranking"] = intent_ranking
        return message


__all__ = ["SklearnIntentClassifier", "SklearnIntentClassifierConfig"]