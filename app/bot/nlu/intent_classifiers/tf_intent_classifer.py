import os
import time
import logging
import threading
from typing import Dict, Any, List, Tuple, Optional
import cloudpickle
import numpy as np
import spacy
import tensorflow as tf
from sklearn.preprocessing import LabelBinarizer
from tensorflow.python.keras import Sequential
from tensorflow.python.layers.core import Dense
from tensorflow.python.layers.core import Dropout
from app.bot.nlu.pipeline import NLUComponent

np.random.seed(1)

logger = logging.getLogger(__name__)


class TfIntentClassifier(NLUComponent):
    """TensorFlow-based intent classifier that implements NLUComponent interface.
    
    This classifier loads TensorFlow and spaCy models once at initialization
    and provides thread-safe prediction operations without global graph state.
    """

    INTENT_RANKING_LENGTH = 3
    MODEL_NAME = "tf_intent_model.hd5"
    LABELS_NAME = "labels.pkl"
    VOCAB_SIZE = 384  # spacy context vector size

    def __init__(self):
        """Initialize classifier with lazy-loaded models and thread safety."""
        self.model: Optional[tf.keras.Model] = None
        self.nlp: Optional[spacy.Language] = None
        self.label_encoder: Optional[LabelBinarizer] = None
        self._lock = threading.RLock()
        self._initialized = False
        self._initialize_models()

    def _initialize_models(self) -> None:
        """Initialize spaCy model at startup (called once in __init__)."""
        try:
            with self._lock:
                if not self._initialized:
                    self.nlp = spacy.load("en")
                    self.label_encoder = LabelBinarizer()
                    self._initialized = True
                    logger.info("TfIntentClassifier models initialized at startup")
        except Exception as e:
            logger.error(f"Failed to initialize models at startup: {e}")
            raise

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train intent classifier for given training data.
        
        Args:
            training_data: List of training examples with 'text' and 'intent' keys.
            model_path: Directory path where trained model artifacts will be saved.
        """
        if not self.nlp or not self.label_encoder:
            raise RuntimeError("Models not initialized. Call _initialize_models() first.")

        def create_model(num_labels: int) -> tf.keras.Model:
            """Define and return tensorflow model.
            
            Args:
                num_labels: Number of intent labels.
                
            Returns:
                Compiled Keras Sequential model.
            """
            model = Sequential()
            model.add(Dense(256, activation=tf.nn.relu, input_shape=(self.VOCAB_SIZE,)))
            model.add(Dropout(0.2))
            model.add(Dense(128, activation=tf.nn.relu))
            model.add(Dropout(0.2))
            model.add(Dense(num_labels, activation=tf.nn.softmax))

            model.compile(
                loss="categorical_crossentropy",
                optimizer="adam",
                metrics=["accuracy"],
            )

            model.summary()
            return model

        # Extract training features
        X = []
        y = []
        for example in training_data:
            if example.get("text", "").strip() == "":
                continue
            X.append(example.get("text"))
            y.append(example.get("intent"))

        # Create spacy doc vector matrix
        x_train = np.array([list(self.nlp(x).vector) for x in X])

        num_labels = len(set(y))
        self.label_encoder.fit(y)
        y_train = self.label_encoder.transform(y)

        # Clear any previous model state
        with self._lock:
            if self.model is not None:
                del self.model
            tf.keras.backend.clear_session()
            time.sleep(3)

            self.model = create_model(num_labels)
            # Start training
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
        
        Args:
            model_path: Directory path containing saved model artifacts.
            
        Returns:
            True if loading succeeded, False otherwise.
        """
        try:
            with self._lock:
                if self.model is not None:
                    del self.model
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

        except Exception as e:
            logger.error(f"Error loading model: {e}")
            return False

    def predict_proba(self, message: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
        """Given a message, predict most probable label.
        
        Thread-safe prediction without global graph state.
        
        Args:
            message: Message dictionary with 'text' key.
            
        Returns:
            Tuple of (sorted_indices, probabilities) arrays.
        """
        if not self.model or not self.nlp:
            raise RuntimeError("Model or spaCy not initialized")

        x_predict = np.array([self.nlp(message.get("text")).vector])
        
        with self._lock:
            # Use eager execution (TF 2.x default) - no graph context needed
            pred_result = self.model.predict(x_predict, verbose=0)
        
        sorted_indices = np.fliplr(np.argsort(pred_result, axis=1))
        return sorted_indices, pred_result[:, sorted_indices]

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and return the extracted information.
        
        Args:
            message: Input message dictionary with 'text' key.
            
        Returns:
            Message dictionary enriched with 'intent' and 'intent_ranking' keys.
        """
        if not message.get("text"):
            return message

        intent = {"name": None, "confidence": 0.0}
        intent_ranking = []

        if self.model and self.label_encoder:
            try:
                intents, probabilities = self.predict_proba(message)
                intents = [
                    self.label_encoder.classes_[intent] for intent in intents.flatten()
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
            except Exception as e:
                logger.error(f"Error during prediction: {e}")
                intent = {"name": None, "confidence": 0.0}
                intent_ranking = []

        message["intent"] = intent
        message["intent_ranking"] = intent_ranking
        return message