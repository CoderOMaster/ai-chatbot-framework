import os
import logging
from typing import Dict, Any, List, Optional, Tuple
import cloudpickle
import numpy as np
from datetime import datetime
from app.bot.nlu.pipeline import NLUComponent

logger = logging.getLogger(__name__)


class SklearnIntentClassifier(NLUComponent):
    """Sklearn-based intent classifier implementing NLUComponent.

    This class adapts an sklearn-style estimator by exposing fit/predict_proba
    methods while retaining the NLUComponent train/load/process API required
    by the pipeline.

    Persisted artifacts:
    - MODEL_NAME: pickled sklearn estimator (cloudpickle)
    - METADATA_NAME: pickled metadata including grid search results and
      pinned numpy/scikit-learn versions for reproducibility.
    """

    INTENT_RANKING_LENGTH = 3
    MODEL_NAME = "sklearn_intent_model.hd5"
    METADATA_NAME = "sklearn_intent_model.metadata.pkl"

    def __init__(self) -> None:
        self.model = None
        self.metadata: Optional[Dict[str, Any]] = None

    def get_spacy_embedding(self, spacy_doc) -> np.ndarray:
        """Return a 1D numpy array for a spaCy Doc vector.

        The returned array is float32 to reduce memory footprint.
        """
        return np.array(spacy_doc.vector, dtype=np.float32)

    # sklearn-like API methods -------------------------------------------------
    def fit(self, X: np.ndarray, y: List[str]) -> None:
        """Fit the underlying sklearn estimator.

        This method expects X to be a 2D numpy array of shape (n_samples, dim).
        """
        if self.model is None:
            raise RuntimeError("No estimator is set to fit. Use train() to run GridSearch or set model manually.")
        self.model.fit(X, y)

    def predict_proba(self, X: Any) -> np.ndarray:
        """Return class probabilities for given inputs.

        X may be either:
        - a numpy array of shape (n_samples, dim), or
        - a mapping-like object with key 'spacy_doc' (single message) as used by process().
        """
        if self.model is None:
            raise RuntimeError("Model not loaded")

        # If caller passed a message dict (from pipeline), extract embedding
        if isinstance(X, dict) and X.get("spacy_doc") is not None:
            emb = self.get_spacy_embedding(X.get("spacy_doc"))
            emb = emb.reshape(1, -1)
            return self.model.predict_proba(emb)

        # Otherwise assume numpy-like input
        return self.model.predict_proba(np.asarray(X))

    # NLUComponent API methods -----------------------------------------------
    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train the classifier using GridSearchCV and persist the best model + metadata.

        This implementation streams spaCy vectors when possible to avoid
        holding the original spaCy Doc objects in memory. It does two passes:
        1) count valid examples and determine embedding dimension
        2) pre-allocate numpy array and fill it row-by-row
        """
        from sklearn.model_selection import GridSearchCV
        from sklearn.svm import SVC
        import importlib

        # First pass: count samples and determine embedding dimension
        valid_examples = []
        embedding_dim: Optional[int] = None
        for ex in training_data:
            text = ex.get("text", "")
            doc = ex.get("spacy_doc")
            intent = ex.get("intent")
            if not text or not text.strip() or doc is None or intent is None:
                continue
            if embedding_dim is None:
                embedding_dim = len(doc.vector)
            valid_examples.append((doc, intent))

        if not valid_examples:
            raise ValueError("No valid training examples provided")

        n_samples = len(valid_examples)
        embedding_dim = int(embedding_dim)

        # Pre-allocate for memory efficiency and stream embeddings into it
        X = np.zeros((n_samples, embedding_dim), dtype=np.float32)
        y: List[str] = []
        for i, (doc, intent) in enumerate(valid_examples):
            X[i] = self.get_spacy_embedding(doc)
            y.append(intent)

        # Determine cross-validation splits based on label frequencies
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

        logger.info("Starting GridSearchCV with %d samples and embedding dim %d", n_samples, embedding_dim)
        classifier.fit(X, y)

        # Persist best estimator and metadata
        if model_path:
            os.makedirs(model_path, exist_ok=True)
            model_file = os.path.join(model_path, self.MODEL_NAME)
            metadata_file = os.path.join(model_path, self.METADATA_NAME)

            # Save best estimator
            with open(model_file, "wb") as f:
                cloudpickle.dump(classifier.best_estimator_, f)

            # Build metadata including pinned versions
            metadata = {
                "saved_at": datetime.utcnow().isoformat() + "Z",
                "best_params": classifier.best_params_,
                "best_score": float(classifier.best_score_),
                "cv_splits": int(cv_splits),
                "param_grid": tuned_parameters,
                # cv_results_ may contain numpy arrays; serialize with cloudpickle
                "cv_results_raw": classifier.cv_results_,
            }

            # Pin numpy and scikit-learn versions for reproducibility
            try:
                import importlib.metadata as importlib_metadata
n            except Exception:
                import importlib_metadata  # type: ignore

            try:
                metadata["numpy_version"] = importlib_metadata.version("numpy")
            except Exception:
                metadata["numpy_version"] = None
            try:
                metadata["scikit_learn_version"] = importlib_metadata.version("scikit-learn")
            except Exception:
                metadata["scikit_learn_version"] = None

            with open(metadata_file, "wb") as f:
                cloudpickle.dump(metadata, f)

            logger.info("Training completed & model written out to %s", model_file)

        self.model = classifier.best_estimator_
        # Store metadata in-memory as well
        try:
            self.metadata = metadata
        except UnboundLocalError:
            self.metadata = None

    def load(self, model_path: str) -> bool:
        """Load trained model and metadata from given path."""
        try:
            model_file = os.path.join(model_path, self.MODEL_NAME)
            with open(model_file, "rb") as f:
                self.model = cloudpickle.load(f)

            metadata_file = os.path.join(model_path, self.METADATA_NAME)
            if os.path.exists(metadata_file):
                with open(metadata_file, "rb") as f:
                    self.metadata = cloudpickle.load(f)
            else:
                self.metadata = None
            return True
        except IOError:
            return False

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and add intent and intent_ranking keys.

        The method is resilient when model is not loaded and will return the
        message unchanged (except for possibly adding empty intent fields).
        """
        if not message.get("text") or not message.get("spacy_doc"):
            return message

        intent = {"name": None, "confidence": 0.0}
        intent_ranking: List[Dict[str, Any]] = []

        if self.model:
            proba = self.predict_proba(message)
            # proba shape is (1, n_classes)
            sorted_indices = np.fliplr(np.argsort(proba, axis=1))
            intents = [self.model.classes_[idx] for idx in sorted_indices.flatten()]
            probabilities = proba.flatten()[np.argsort(proba, axis=1).flatten()[::-1]]

            if len(intents) > 0 and len(probabilities) > 0:
                ranking = list(zip(list(intents), list(probabilities)))[: self.INTENT_RANKING_LENGTH]

                intent = {"intent": ranking[0][0], "confidence": float(ranking[0][1])}
                intent_ranking = [
                    {"intent": intent_name, "confidence": float(score)}
                    for intent_name, score in ranking
                ]

        message["intent"] = intent
        message["intent_ranking"] = intent_ranking
        return message