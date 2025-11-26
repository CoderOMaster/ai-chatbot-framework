import os
import time
import logging
import threading
from typing import Dict, Any, List, Tuple
import cloudpickle
import numpy as np
import spacy
from sklearn.preprocessing import LabelBinarizer
from app.bot.nlu.pipeline import NLUComponent

np.random.seed(1)

logger = logging.getLogger(__name__)


class TfIntentClassifier(NLUComponent):
    """TensorFlow-based intent classifier that implements NLUComponent interface.

    Note: TensorFlow is imported lazily only when training/loading/predicting to
    avoid adding TF as a dependency for latency-sensitive environments that
    only need the component interface. If TensorFlow is not available and one
    of those operations is called, an informative ImportError is raised.
    """

    INTENT_RANKING_LENGTH = 3
    MODEL_NAME = "tf_intent_model.hd5"
    LABELS_NAME = "labels.pkl"

    def __init__(self) -> None:
        self.model = None
        # spacy load remains eager; if this is also problematic consider
        # moving it to lazy-loading as well in future refactors.
        self.nlp = spacy.load("en")
        self.label_encoder = LabelBinarizer()
        self._tf = None
        self._predict_lock = threading.Lock()

    def _ensure_tf(self):
        """Lazily import TensorFlow and expose it on the instance.

        Raises:
            ImportError: if TensorFlow cannot be imported.
        """
        if self._tf is None:
            try:
                import tensorflow as tf  # imported locally to avoid module-level TF import

                self._tf = tf
            except Exception as e:  # pragma: no cover - environment dependent
                raise ImportError(
                    "TensorFlow is required for TfIntentClassifier but could not be "
                    f"be imported: {e}. Use this component only in environments "
                    "that include TensorFlow (e.g., training-worker)."
                )
        return self._tf

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train intent classifier for given training data and save to model_path.

        This method will import TensorFlow at runtime. It is intended to be
        executed in a training-worker process where TF is available.
        """
        tf = self._ensure_tf()

        def create_model(vocab_size: int, num_labels: int):
            """Define and return a compiled tf.keras model."""
            model = tf.keras.Sequential()
            model.add(tf.keras.layers.Dense(256, activation=tf.nn.relu, input_shape=(vocab_size,)))
            model.add(tf.keras.layers.Dropout(0.2))
            model.add(tf.keras.layers.Dense(128, activation=tf.nn.relu))
            model.add(tf.keras.layers.Dropout(0.2))
            model.add(tf.keras.layers.Dense(num_labels, activation=tf.nn.softmax))

            model.compile(
                loss="categorical_crossentropy",
                optimizer="adam",
                metrics=["accuracy"],
            )

            model.summary()
            return model

        # Extract training features
        X: List[str] = []
        y: List[str] = []
        for example in training_data:
            if example.get("text", "").strip() == "":
                continue
            X.append(example.get("text"))
            y.append(example.get("intent"))

        # spacy context vector size (depends on model used)
        vocab_size = 384

        # create spacy doc vector matrix
        x_train = np.array([list(self.nlp(text).vector) for text in X])

        num_labels = len(set(y))
        self.label_encoder.fit(y)
        y_train = self.label_encoder.transform(y)

        # release any previous model and clear backend session
        if self.model is not None:
            self.model = None
        tf.keras.backend.clear_session()
        time.sleep(1)

        self.model = create_model(vocab_size, num_labels)
        # start training
        self.model.fit(x_train, y_train, shuffle=True, epochs=300, verbose=1)

        if model_path:
            # Save model
            model_file = os.path.join(model_path, self.MODEL_NAME)
            tf.keras.models.save_model(self.model, model_file)
            logger.info(f"TF Model written out to {model_file}")

            # Save label encoder
            labels_file = os.path.join(model_path, self.LABELS_NAME)
            with open(labels_file, "wb") as f:
                cloudpickle.dump(self.label_encoder, f)
            logger.info(f"Labels written out to {labels_file}")

    def load(self, model_path: str) -> bool:
        """Load trained model from given path.

        Returns True on success, False otherwise. TensorFlow is imported lazily.
        """
        try:
            tf = self._ensure_tf()

            # Clear any previous model
            if self.model is not None:
                self.model = None
            tf.keras.backend.clear_session()

            # Load model
            model_file = os.path.join(model_path, self.MODEL_NAME)
            self.model = tf.keras.models.load_model(model_file, compile=True)
            logger.info("TF model loaded")

            # Load label encoder
            labels_file = os.path.join(model_path, self.LABELS_NAME)
            with open(labels_file, "rb") as f:
                self.label_encoder = cloudpickle.load(f)
            logger.info("Labels model loaded")
            return True

        except Exception as e:  # pragma: no cover - operational error
            logger.error(f"Error loading model: {e}")
            return False

    def predict_proba(self, message: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
        """Given a message, predict label probabilities.

        Returns a tuple of (sorted_indices, probabilities). This method will
        import TensorFlow lazily if needed. Predictions are protected by a
        lock to avoid concurrent predict() calls provoking runtime issues.
        """
        if self.model is None:
            raise RuntimeError("Model is not loaded. Call load(...) before predict_proba.")

        # ensure TF is available for backend-dependent behavior
        self._ensure_tf()

        x_predict = [self.nlp(message.get("text")).vector]

        with self._predict_lock:
            pred_result = self.model.predict(np.array([x_predict[0]]))

        sorted_indices = np.fliplr(np.argsort(pred_result, axis=1))
        return sorted_indices, pred_result[:, sorted_indices]

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and attach intent and intent_ranking to it.

        This method avoids importing TensorFlow unless a model has been loaded
        previously.
        """
        if not message.get("text"):
            return message

        intent = {"name": None, "confidence": 0.0}
        intent_ranking: List[Dict[str, Any]] = []

        if self.model:
            try:
                intents_idx, probabilities = self.predict_proba(message)
                intents = [
                    self.label_encoder.classes_[idx] for idx in intents_idx.flatten()
                ]
                probabilities = probabilities.flatten()

                if len(intents) > 0 and len(probabilities) > 0:
                    ranking = list(zip(list(intents), list(probabilities)))
                    ranking = ranking[: self.INTENT_RANKING_LENGTH]

                    intent = {
                        "intent": intents[0],
                        "confidence": float("%.2f" % probabilities[0]),
                    }
                    intent_ranking = [
                        {"intent": intent_name, "confidence": float("%.2f" % score)}
                        for intent_name, score in ranking
                    ]
                else:
                    intent = {"name": None, "confidence": 0.0}
                    intent_ranking = []

            except Exception as e:  # pragma: no cover - runtime prediction error
                logger.error(f"Error during prediction: {e}")
                intent = {"name": None, "confidence": 0.0}
                intent_ranking = []

        message["intent"] = intent
        message["intent_ranking"] = intent_ranking
        return message