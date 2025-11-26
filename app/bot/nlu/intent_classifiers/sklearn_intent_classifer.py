import os
from typing import Any, Dict, List, Optional, Tuple
import cloudpickle
import numpy as np
import logging

from app.bot.nlu.pipeline import NLUComponent, ModelPath, TrainingData, MessageDict

logger = logging.getLogger(__name__)


class SklearnIntentClassifier(NLUComponent):
    """Sklearn-based intent classifier.

    Notes:
    - Training can be expensive; keep calls to train() and heavy scikit-learn imports
      within a dedicated training worker/process. This class keeps the train API
      for offline training but ensures inference code avoids importing heavy
      libraries at module import time.
    - model_path is intentionally a parameter to train/load so the caller (CI/launcher)
      can control where artifacts are stored (image-baked path, mounted volume, or
      object storage via a ModelStorage abstraction).
    """

    INTENT_RANKING_LENGTH = 3
    DEFAULT_MODEL_NAME = "sklearn_intent_model.pkl"

    def __init__(self, model_name: Optional[str] = None) -> None:
        """Create classifier instance.

        Args:
            model_name: optional filename to use when saving/loading the model.
                        If not provided DEFAULT_MODEL_NAME will be used.
        """
        self.model: Optional[Any] = None
        self.model_name = model_name or self.DEFAULT_MODEL_NAME

    def get_spacy_embedding(self, spacy_doc: Any) -> np.ndarray:
        """Return dense embedding for a spaCy Doc.

        Keeping this small and pure so inference is fast. Expects the provided
        object to expose a ``vector`` attribute as spaCy's Doc does.
        """
        return np.array(spacy_doc.vector)

    def _save_model_bytes(self, data: bytes, model_path: ModelPath) -> None:
        """Persist serialized bytes to either a filesystem path or a ModelStorage.

        The ModelPath abstraction allows callers to provide different storage
        backends without the component needing to know about them.
        """
        if hasattr(model_path, "save_bytes"):
            # type: ignore[attr-defined]
            model_path.save_bytes(self.model_name, data)
            return

        # treat model_path as filesystem path
        if isinstance(model_path, (str, os.PathLike)):
            os.makedirs(model_path, exist_ok=True)
            path = os.path.join(str(model_path), self.model_name)
            with open(path, "wb") as f:
                f.write(data)
            return

        raise ValueError("Unsupported model_path type for saving model")

    def _load_model_bytes(self, model_path: ModelPath) -> Optional[bytes]:
        """Load serialized model bytes from filesystem or ModelStorage.

        Returns bytes when successful or None when the file does not exist.
        """
        if hasattr(model_path, "load_bytes"):
            # type: ignore[attr-defined]
            try:
                return model_path.load_bytes(self.model_name)
            except Exception:
                return None

        if isinstance(model_path, (str, os.PathLike)):
            path = os.path.join(str(model_path), self.model_name)
            try:
                with open(path, "rb") as f:
                    return f.read()
            except IOError:
                return None

        return None

    def train(self, training_data: TrainingData, model_path: ModelPath) -> None:
        """Train the classifier using provided training data and persist the model.

        This method intentionally performs heavy operations (GridSearchCV, model.fit)
        and should only be invoked by an offline training worker.
        """
        # local import to avoid pulling heavy deps into request-time code
        from sklearn.model_selection import GridSearchCV
        from sklearn.svm import SVC

        X_docs: List[Any] = []
        y: List[str] = []
        for example in training_data:
            text = example.get("text", "")
            if not text or not text.strip():
                continue
            doc = example.get("spacy_doc")
            if doc is None:
                continue
            X_docs.append(doc)
            y.append(example.get("intent"))

        if not X_docs or not y:
            logger.warning("No training data provided to SklearnIntentClassifier.train")
            return

        X = np.stack([self.get_spacy_embedding(doc) for doc in X_docs])

        # compute cross-validation splits defensively
        _, counts = np.unique(y, return_counts=True)
        cv_splits = max(2, min(5, int(np.min(counts) // 5))) if counts.size > 0 else 2

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

        # serialize best estimator to bytes and save via model_path
        model_bytes = cloudpickle.dumps(classifier.best_estimator_)
        self._save_model_bytes(model_bytes, model_path)
        logger.info("Training completed & model written out to %s (via model_path)", self.model_name)

        # keep a reference to the fitted estimator for immediate use if desired
        self.model = classifier.best_estimator_

    def load(self, model_path: ModelPath) -> bool:
        """Load a pre-trained model from the given model_path.

        Returns True on success, False otherwise. This method supports both
        local filesystem paths and ModelStorage implementations.
        """
        data = self._load_model_bytes(model_path)
        if not data:
            logger.debug("Model not found at %s", model_path)
            return False

        try:
            self.model = cloudpickle.loads(data)
            logger.info("Loaded sklearn intent model: %s", self.model_name)
            return True
        except Exception:
            logger.exception("Failed to deserialize sklearn model")
            return False

    def predict_proba(self, message: MessageDict) -> Tuple[np.ndarray, np.ndarray]:
        """Return (sorted_indices, probabilities) arrays for the given message.

        The sorted_indices array contains class indices sorted in descending order
        of probability and probabilities contains the corresponding probability
        scores. Raises ValueError when the model has not been loaded.
        """
        if self.model is None:
            raise ValueError("Model not loaded. Call load() before predict_proba.")

        embedding = self.get_spacy_embedding(message.get("spacy_doc"))
        pred_result = self.model.predict_proba([embedding])
        sorted_indices = np.fliplr(np.argsort(pred_result, axis=1))
        return sorted_indices, pred_result[:, sorted_indices]

    def process(self, message: MessageDict) -> MessageDict:
        """Process a message and attach intent and intent_ranking fields.

        If no model is loaded this returns the message unchanged except for
        explicit intent fields which remain defaulted to None/confidence 0.0.
        """
        if not message.get("text") or not message.get("spacy_doc"):
            return message

        intent: Dict[str, Any] = {"name": None, "confidence": 0.0}
        intent_ranking: List[Dict[str, Any]] = []

        if self.model is None:
            message["intent"] = intent
            message["intent_ranking"] = intent_ranking
            return message

        try:
            intents_idx, probabilities = self.predict_proba(message)
        except Exception:
            logger.exception("Error during intent prediction")
            message["intent"] = intent
            message["intent_ranking"] = intent_ranking
            return message

        # flatten indices and probabilities and map indices to class labels
        intents = [self.model.classes_[int(i)] for i in intents_idx.flatten()]
        probs = probabilities.flatten()

        if len(intents) > 0 and len(probs) > 0:
            ranking = list(zip(list(intents), list(probs)))[: self.INTENT_RANKING_LENGTH]
            intent = {"intent": ranking[0][0], "confidence": float(ranking[0][1])}
            intent_ranking = [
                {"intent": name, "confidence": float(score)} for name, score in ranking
            ]

        message["intent"] = intent
        message["intent_ranking"] = intent_ranking
        return message