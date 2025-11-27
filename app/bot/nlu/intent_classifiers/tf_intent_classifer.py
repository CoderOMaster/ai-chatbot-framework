import json
import os
import time
import logging
import threading
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import spacy
from sklearn.preprocessing import LabelBinarizer
from pydantic import BaseSettings, Field
import cloudpickle

from app.bot.nlu.pipeline import NLUComponent

logger = logging.getLogger(__name__)


class TFSettings(BaseSettings):
    """Configuration for TensorFlow training parameters read from environment.

    Environment variables:
        TF_EPOCHS: number of training epochs (default: 300)
        TF_BATCH_SIZE: batch size used for training (default: 32)
    """

    epochs: int = Field(300, env="TF_EPOCHS")
    batch_size: int = Field(32, env="TF_BATCH_SIZE")


# Read settings at import-time so callers can override by passing a different
# TFSettings instance to the classifier if needed.
DEFAULT_TF_SETTINGS = TFSettings()


class TfIntentClassifier(NLUComponent):
    """TensorFlow-based intent classifier that implements NLUComponent interface.

    This class lazily imports TensorFlow so that the package can be optional
    during cold-start (training/load/predict functionality will raise a
    RuntimeError if TF is not present). Label encoder metadata is persisted
    to a JSON sidecar for portability; legacy pickled label encoders are
    still supported when loading.
    """

    INTENT_RANKING_LENGTH = 3
    MODEL_NAME = "tf_intent_model.hd5"
    LABELS_NAME_JSON = "labels.json"
    LABELS_NAME_PKL = "labels.pkl"

    def __init__(self, settings: Optional[TFSettings] = None) -> None:
        self._settings = settings or DEFAULT_TF_SETTINGS
        self._tf = None  # lazily imported tensorflow module
        self._predict_lock = threading.Lock()
        self.model = None
        self.nlp = spacy.load("en")
        self.label_encoder = LabelBinarizer()

    def _ensure_tf(self):
        """Import TensorFlow when required. Raises RuntimeError if unavailable.
        The import is cached on the instance to avoid repeated work.
        """
        if self._tf is not None:
            return self._tf
        try:
            import tensorflow as tf

            self._tf = tf
            return self._tf
        except Exception as e:  # ImportError or other failures
            logger.debug("TensorFlow import failed: %s", e)
            raise RuntimeError(
                "TensorFlow is required for TfIntentClassifier but is not available."
            )

    @staticmethod
    def _create_model(tf_mod, vocab_size: int, num_labels: int):
        """Factory that creates and compiles a Keras model using the given
        tensorflow module. Kept separate to make import side-effects minimal.
        """
        from tensorflow.keras import Sequential
        from tensorflow.keras.layers import Dense, Dropout

        model = Sequential()
        model.add(Dense(256, activation=tf_mod.nn.relu, input_shape=(vocab_size,)))
        model.add(Dropout(0.2))
        model.add(Dense(128, activation=tf_mod.nn.relu))
        model.add(Dropout(0.2))
        model.add(Dense(num_labels, activation=tf_mod.nn.softmax))

        model.compile(loss="categorical_crossentropy", optimizer="adam", metrics=["accuracy"])
        return model

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train intent classifier and persist model and label metadata.

        Args:
            training_data: list of examples with 'text' and 'intent' fields.
            model_path: directory to write model and labels files to.
        """
        tf = self._ensure_tf()

        X: List[str] = []
        y: List[str] = []
        for example in training_data:
            text = example.get("text", "").strip()
            if not text:
                continue
            X.append(text)
            y.append(example.get("intent"))

        # fixed spacy vector size used by the preloaded model
        vocab_size = 384
        x_train = np.array([self.nlp(text).vector for text in X])

        num_labels = len(set(y))
        self.label_encoder.fit(y)
        y_train = self.label_encoder.transform(y)

        # clear any previous state
        if hasattr(self, "model") and self.model is not None:
            try:
                del self.model
            except Exception:
                logger.debug("Failed to delete previous model instance during training")
        tf.keras.backend.clear_session()
        time.sleep(0.5)

        # build and train model
        self.model = self._create_model(tf, vocab_size, num_labels)
        self.model.fit(
            x_train,
            y_train,
            shuffle=True,
            epochs=self._settings.epochs,
            batch_size=self._settings.batch_size,
            verbose=1,
        )

        if model_path:
            os.makedirs(model_path, exist_ok=True)
            model_file = os.path.join(model_path, self.MODEL_NAME)
            tf.keras.models.save_model(self.model, model_file)
            logger.info("TF Model written out to %s", model_file)

            # write labels JSON sidecar for portability
            labels_file_json = os.path.join(model_path, self.LABELS_NAME_JSON)
            labels_payload = {"classes": self.label_encoder.classes_.tolist()}
            with open(labels_file_json, "w", encoding="utf-8") as f:
                json.dump(labels_payload, f, ensure_ascii=False, indent=2)
            logger.info("Labels JSON written out to %s", labels_file_json)

            # also write legacy pickle for backward compatibility
            labels_file_pkl = os.path.join(model_path, self.LABELS_NAME_PKL)
            try:
                with open(labels_file_pkl, "wb") as f:
                    cloudpickle.dump(self.label_encoder, f)
                logger.info("Legacy labels pickle written out to %s", labels_file_pkl)
            except Exception:
                logger.debug("Failed to write legacy labels pickle; continuing")

    def load(self, model_path: str) -> bool:
        """Load model and label metadata from model_path.

        Returns True on success, False otherwise.
        """
        try:
            tf = self._ensure_tf()

            # clear any previous model
            if hasattr(self, "model") and self.model is not None:
                try:
                    del self.model
                except Exception:
                    logger.debug("Failed to delete previous model instance during load")
            tf.keras.backend.clear_session()

            model_file = os.path.join(model_path, self.MODEL_NAME)
            self.model = tf.keras.models.load_model(model_file, compile=True)
            logger.info("TF model loaded from %s", model_file)

            # Load labels: prefer JSON sidecar, fall back to legacy pickle
            labels_file_json = os.path.join(model_path, self.LABELS_NAME_JSON)
            labels_file_pkl = os.path.join(model_path, self.LABELS_NAME_PKL)

            if os.path.exists(labels_file_json):
                with open(labels_file_json, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                classes = payload.get("classes", [])
                # sklearn expects an ndarray for classes_
                self.label_encoder.classes_ = np.array(classes)
                logger.info("Labels loaded from JSON %s", labels_file_json)
            elif os.path.exists(labels_file_pkl):
                with open(labels_file_pkl, "rb") as f:
                    self.label_encoder = cloudpickle.load(f)
                logger.info("Labels loaded from legacy pickle %s", labels_file_pkl)
            else:
                logger.warning("No label metadata found at %s", model_path)

            return True
        except Exception as e:
            logger.error("Error loading TF intent classifier: %s", e)
            return False

    def predict_proba(self, message: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
        """Return (sorted_indices, probabilities) for the given message.

        Raises RuntimeError if model or TensorFlow is unavailable.
        """
        if self.model is None:
            raise RuntimeError("Model is not loaded; call load() before predict_proba")
        self._ensure_tf()

        x_vec = np.array([self.nlp(message.get("text", "")).vector])
        with self._predict_lock:
            pred_result = self.model.predict(x_vec)
        sorted_indices = np.fliplr(np.argsort(pred_result, axis=1))
        # return shape compatible with previous implementation
        return sorted_indices, pred_result[:, sorted_indices]

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and append intent and intent_ranking fields.

        The method is tolerant to missing models and will leave intent fields as
        defaults if prediction cannot be performed.
        """
        if not message.get("text"):
            return message

        intent: Dict[str, Any] = {"name": None, "confidence": 0.0}
        intent_ranking: List[Dict[str, Any]] = []

        if self.model is not None:
            try:
                intents_idx, probabilities = self.predict_proba(message)
                intents = [
                    self.label_encoder.classes_[i] for i in intents_idx.flatten()
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
                        {"intent": name, "confidence": float("%.2f" % score)}
                        for name, score in ranking
                    ]
            except Exception:
                logger.exception("Prediction failed in TfIntentClassifier")

        message["intent"] = intent
        message["intent_ranking"] = intent_ranking
        return message