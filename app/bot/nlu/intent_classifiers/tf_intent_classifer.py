import os
import time
import logging
from typing import Any, Dict, List, Optional, Tuple

import cloudpickle
import numpy as np
import spacy
from sklearn.preprocessing import LabelBinarizer

from app.bot.nlu.pipeline import NLUComponent

np.random.seed(1)

logger = logging.getLogger(__name__)
_TF_MODULE: Optional[Any] = None


def _get_tf_module() -> Any:
    """Lazily import TensorFlow when it is first needed to avoid loading it in latency-sensitive Lambdas."""
    global _TF_MODULE
    if _TF_MODULE is None:
        import tensorflow as tf  # noqa: WPS433 (delayed import)

        _TF_MODULE = tf
    return _TF_MODULE


class TfIntentClassifier(NLUComponent):
    """TensorFlow-based intent classifier that implements ``NLUComponent`` interface."""

    INTENT_RANKING_LENGTH = 3
    MODEL_NAME = "tf_intent_model.hd5"
    LABELS_NAME = "labels.pkl"

    def __init__(self) -> None:
        self.model: Optional[Any] = None
        self.nlp = spacy.load("en")
        self.label_encoder = LabelBinarizer()

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train the intent classifier using TensorFlow and persist the model to disk."""
        tf = _get_tf_module()

        def create_model() -> Any:
            """Define and return a fresh TensorFlow keras model instance."""
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

        # Extract training features and targets
        X: List[str] = []
        y: List[str] = []
        for example in training_data:
            text = example.get("text", "").strip()
            if not text:
                continue
            X.append(text)
            y.append(example.get("intent"))

        vocab_size = 384
        x_train = np.array([self.nlp(text).vector for text in X])

        num_labels = len(set(y))
        self.label_encoder.fit(y)
        y_train = self.label_encoder.transform(y)

        if self.model is not None:
            del self.model
        tf.keras.backend.clear_session()
        time.sleep(3)

        self.model = create_model()
        self.model.fit(x_train, y_train, shuffle=True, epochs=300, verbose=1)

        if model_path:
            model_file = os.path.join(model_path, self.MODEL_NAME)
            tf.keras.models.save_model(self.model, model_file)
            logger.info(f"TF Model written out to {model_file}")

            labels_file = os.path.join(model_path, self.LABELS_NAME)
            with open(labels_file, "wb") as labels_handle:
                cloudpickle.dump(self.label_encoder, labels_handle)
            logger.info(f"Labels written out to {labels_file}")

    def load(self, model_path: str) -> bool:
        """Load a previously trained TensorFlow intent classification model from disk."""
        tf = _get_tf_module()
        try:
            if self.model is not None:
                del self.model
            tf.keras.backend.clear_session()

            model_file = os.path.join(model_path, self.MODEL_NAME)
            self.model = tf.keras.models.load_model(model_file, compile=True)
            logger.info("TF model loaded")

            labels_file = os.path.join(model_path, self.LABELS_NAME)
            with open(labels_file, "rb") as labels_handle:
                self.label_encoder = cloudpickle.load(labels_handle)
            logger.info("Labels model loaded")
            return True

        except Exception as exc:
            logger.error(f"Error loading model: {exc}")
            return False

    def predict_proba(self, message: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
        """Return sorted intent indices and their associated probabilities for the input message."""
        if not self.model:
            raise RuntimeError("Model has not been loaded or trained yet.")

        x_predict = np.array([self.nlp(message.get("text", "")).vector], dtype=np.float32)
        pred_result = self.model.predict(x_predict)
        sorted_indices = np.fliplr(np.argsort(pred_result, axis=1))
        return sorted_indices, pred_result[:, sorted_indices]

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single message to determine intent ranking information."""
        if not message.get("text"):
            return message

        intent: Dict[str, Any] = {"name": None, "confidence": 0.0}
        intent_ranking: List[Dict[str, Any]] = []

        if self.model:
            intents, probabilities = self.predict_proba(message)
            intents = [self.label_encoder.classes_[intent_idx] for intent_idx in intents.flatten()]
            probabilities = probabilities.flatten()

            if intents and probabilities.size:
                ranking = list(zip(intents, probabilities))[: self.INTENT_RANKING_LENGTH]
                intent = {
                    "intent": ranking[0][0],
                    "confidence": float("%.2f" % ranking[0][1]),
                }
                intent_ranking = [
                    {"intent": intent_name, "confidence": float("%.2f" % score)}
                    for intent_name, score in ranking
                ]

        message["intent"] = intent
        message["intent_ranking"] = intent_ranking
        return message


__all__ = ["TfIntentClassifier"]