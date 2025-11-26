import os
import time
import logging
from typing import Dict, Any, List, Tuple
import cloudpickle
import numpy as np
import spacy
import tensorflow as tf
from sklearn.preprocessing import LabelBinarizer
from tensorflow.keras import Sequential
from tensorflow.keras.layers import Dense, Dropout
from shared.nlu.pipeline import NLUComponent

np.random.seed(1)

logger = logging.getLogger(__name__)


class TfIntentClassifier(NLUComponent):
    """TensorFlow-based intent classifier that implements NLUComponent interface.
    
    This classifier uses TensorFlow 2.x with Keras API for intent classification.
    Supports GPU acceleration when available. Designed for deployment as a
    microservice with configurable resource constraints.
    """

    INTENT_RANKING_LENGTH = 3
    MODEL_NAME = "tf_intent_model.hd5"
    LABELS_NAME = "labels.pkl"

    def __init__(self, use_gpu: bool = True) -> None:
        """Initialize the TensorFlow intent classifier.
        
        Args:
            use_gpu: Enable GPU support if available. Defaults to True.
        """
        self.model: tf.keras.Model = None
        self.nlp = spacy.load("en")
        self.label_encoder = LabelBinarizer()
        self.use_gpu = use_gpu
        self._configure_gpu()

    def _configure_gpu(self) -> None:
        """Configure GPU support for TensorFlow 2.x.
        
        Sets memory growth to avoid OOM errors and logs GPU availability.
        """
        if not self.use_gpu:
            tf.config.set_visible_devices([], 'GPU')
            logger.info("GPU disabled for TensorFlow")
            return

        gpus = tf.config.list_physical_devices('GPU')
        if gpus:
            try:
                for gpu in gpus:
                    tf.config.experimental.set_memory_growth(gpu, True)
                logger.info(f"GPU support enabled: {len(gpus)} GPU(s) detected")
            except RuntimeError as e:
                logger.warning(f"GPU configuration failed: {e}")
        else:
            logger.info("No GPU detected, using CPU")

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train intent classifier for given training data.
        
        Args:
            training_data: List of training examples with 'text' and 'intent' keys.
            model_path: Directory path to save trained model and labels.
        """

        def create_model() -> tf.keras.Model:
            """Define and return TensorFlow 2.x Keras model.
            
            Returns:
                Compiled Sequential model for intent classification.
            """
            model = Sequential()
            model.add(Dense(256, activation=tf.nn.relu, input_shape=(vocab_size,)))
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

        # spacy context vector size
        vocab_size = 384

        # create spacy doc vector matrix
        x_train = np.array([list(self.nlp(x).vector) for x in X])

        num_labels = len(set(y))
        self.label_encoder.fit(y)
        y_train = self.label_encoder.transform(y)

        if self.model is not None:
            del self.model
        tf.keras.backend.clear_session()
        time.sleep(3)

        self.model = create_model()
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
        
        Args:
            model_path: Directory path containing saved model and labels.
            
        Returns:
            True if model loaded successfully, False otherwise.
        """
        try:
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
        
        Args:
            message: Dictionary containing 'text' key with input message.
            
        Returns:
            Tuple of (sorted_indices, probabilities) arrays.
        """
        x_predict = [self.nlp(message.get("text")).vector]
        pred_result = self.model.predict(np.array([x_predict[0]]))
        sorted_indices = np.fliplr(np.argsort(pred_result, axis=1))
        return sorted_indices, pred_result[:, sorted_indices]

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and return the extracted information.
        
        Args:
            message: Input message dictionary with 'text' key.
            
        Returns:
            Message dictionary with added 'intent' and 'intent_ranking' keys.
        """
        if not message.get("text"):
            return message

        intent = {"name": None, "confidence": 0.0}
        intent_ranking = []

        if self.model:
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

        message["intent"] = intent
        message["intent_ranking"] = intent_ranking
        return message