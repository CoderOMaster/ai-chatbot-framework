"""TensorFlow 2.x-based intent classifier with GPU support and batch prediction."""

import os
import logging
from typing import Dict, Any, List, Tuple, Optional
import cloudpickle
import numpy as np
import spacy
import tensorflow as tf
from sklearn.preprocessing import LabelBinarizer
from app.bot.nlu.pipeline import NLUComponent

logger = logging.getLogger(__name__)

# Set random seeds for reproducibility
np.random.seed(1)
tf.random.set_seed(1)


class TfIntentClassifier(NLUComponent):
    """TensorFlow 2.x intent classifier with eager execution and GPU support.
    
    Features:
    - TF 2.x eager execution (no graph/session management)
    - GPU acceleration support
    - Batch prediction capability
    - Model serving optimization
    - Optimized for inference performance
    """

    INTENT_RANKING_LENGTH = 3
    MODEL_NAME = "tf_intent_model"
    LABELS_NAME = "labels.pkl"
    VOCAB_SIZE = 384  # spacy en_core_web_md vector size

    def __init__(self, name: str = "tf_intent_classifier", enable_gpu: bool = True):
        """Initialize TensorFlow intent classifier.
        
        Args:
            name: Component name identifier
            enable_gpu: Whether to enable GPU acceleration
        """
        super().__init__(name=name, parallelizable=False)
        self.model: Optional[tf.keras.Model] = None
        self.nlp: Optional[spacy.Language] = None
        self.label_encoder: Optional[LabelBinarizer] = None
        self.enable_gpu = enable_gpu
        self._configure_gpu()
        self._load_spacy_model()

    def _configure_gpu(self) -> None:
        """Configure GPU settings for TensorFlow."""
        if self.enable_gpu:
            gpus = tf.config.list_physical_devices("GPU")
            if gpus:
                try:
                    for gpu in gpus:
                        tf.config.experimental.set_memory_growth(gpu, True)
                    logger.info(f"GPU acceleration enabled: {len(gpus)} GPU(s) detected")
                except RuntimeError as e:
                    logger.warning(f"GPU configuration failed: {e}")
        else:
            tf.config.set_visible_devices([], "GPU")
            logger.info("GPU acceleration disabled")

    def _load_spacy_model(self) -> None:
        """Load spacy language model for text vectorization."""
        try:
            self.nlp = spacy.load("en_core_web_md")
            logger.info("Spacy model loaded: en_core_web_md")
        except OSError:
            logger.warning("en_core_web_md not found, attempting en_core_web_sm")
            try:
                self.nlp = spacy.load("en_core_web_sm")
                logger.info("Spacy model loaded: en_core_web_sm")
            except OSError:
                logger.error("No spacy model available. Install with: python -m spacy download en_core_web_md")
                raise

    def _create_model(self, num_labels: int) -> tf.keras.Model:
        """Create and compile TensorFlow 2.x model with eager execution.
        
        Args:
            num_labels: Number of intent labels
            
        Returns:
            Compiled Keras model
        """
        model = tf.keras.Sequential([
            tf.keras.layers.Dense(256, activation="relu", input_shape=(self.VOCAB_SIZE,)),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.Dense(128, activation="relu"),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.Dense(num_labels, activation="softmax"),
        ])

        model.compile(
            loss="categorical_crossentropy",
            optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
            metrics=["accuracy"],
        )

        return model

    def _vectorize_texts(self, texts: List[str]) -> np.ndarray:
        """Vectorize texts using spacy embeddings.
        
        Args:
            texts: List of text strings
            
        Returns:
            Array of shape (len(texts), VOCAB_SIZE)
        """
        if not self.nlp:
            raise RuntimeError("Spacy model not loaded")
        
        vectors = np.array([self.nlp(text).vector for text in texts], dtype=np.float32)
        return vectors

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train intent classifier with given training data.
        
        Args:
            training_data: List of training examples with 'text' and 'intent' keys
            model_path: Path to save trained model and labels
        """
        # Extract and validate training data
        texts = []
        intents = []
        
        for example in training_data:
            text = example.get("text", "").strip()
            intent = example.get("intent")
            if text and intent:
                texts.append(text)
                intents.append(intent)

        if not texts:
            logger.error("No valid training data provided")
            return

        logger.info(f"Training with {len(texts)} examples, {len(set(intents))} unique intents")

        # Vectorize texts
        x_train = self._vectorize_texts(texts)

        # Encode labels
        self.label_encoder = LabelBinarizer()
        y_train = self.label_encoder.fit_transform(intents)

        # Create and train model
        num_labels = len(self.label_encoder.classes_)
        self.model = self._create_model(num_labels)

        logger.info("Starting model training...")
        self.model.fit(
            x_train,
            y_train,
            shuffle=True,
            epochs=300,
            batch_size=32,
            verbose=1,
            validation_split=0.1,
        )

        # Save model and labels
        if model_path:
            os.makedirs(model_path, exist_ok=True)
            
            # Save model in SavedModel format (TF Serving compatible)
            model_file = os.path.join(model_path, self.MODEL_NAME)
            self.model.save(model_file, save_format="tf")
            logger.info(f"TensorFlow model saved to {model_file}")

            # Save label encoder
            labels_file = os.path.join(model_path, self.LABELS_NAME)
            with open(labels_file, "wb") as f:
                cloudpickle.dump(self.label_encoder, f)
            logger.info(f"Label encoder saved to {labels_file}")

    def load(self, model_path: str) -> bool:
        """Load trained model from disk.
        
        Args:
            model_path: Path to load model from
            
        Returns:
            True if load successful, False otherwise
        """
        try:
            # Load model (TF 2.x eager execution, no session needed)
            model_file = os.path.join(model_path, self.MODEL_NAME)
            self.model = tf.keras.models.load_model(model_file)
            logger.info(f"TensorFlow model loaded from {model_file}")

            # Load label encoder
            labels_file = os.path.join(model_path, self.LABELS_NAME)
            with open(labels_file, "rb") as f:
                self.label_encoder = cloudpickle.load(f)
            logger.info(f"Label encoder loaded from {labels_file}")

            return True

        except Exception as e:
            logger.error(f"Error loading model: {e}")
            return False

    def predict_proba(self, texts: List[str]) -> Tuple[np.ndarray, np.ndarray]:
        """Predict intent probabilities for batch of texts.
        
        Args:
            texts: List of text strings
            
        Returns:
            Tuple of (sorted_indices, probabilities)
        """
        if not self.model or not self.label_encoder:
            raise RuntimeError("Model not loaded")

        # Vectorize texts
        x_predict = self._vectorize_texts(texts)

        # Predict with eager execution (no graph context needed)
        predictions = self.model.predict(x_predict, verbose=0)

        # Sort by probability (descending)
        sorted_indices = np.fliplr(np.argsort(predictions, axis=1))
        
        return sorted_indices, predictions

    def predict_batch(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process batch of messages for efficient inference.
        
        Args:
            messages: List of message dictionaries
            
        Returns:
            List of processed messages with intent predictions
        """
        if not self.model:
            return messages

        # Extract texts
        texts = [msg.get("text", "") for msg in messages]
        
        # Filter out empty texts
        valid_indices = [i for i, text in enumerate(texts) if text.strip()]
        
        if not valid_indices:
            return messages

        valid_texts = [texts[i] for i in valid_indices]

        # Batch predict
        sorted_indices, probabilities = self.predict_proba(valid_texts)

        # Update messages with predictions
        for batch_idx, msg_idx in enumerate(valid_indices):
            intents = sorted_indices[batch_idx]
            probs = probabilities[batch_idx]

            intent_names = [
                self.label_encoder.classes_[intent] for intent in intents
            ]
            
            ranking = list(zip(intent_names, probs))
            ranking = ranking[:self.INTENT_RANKING_LENGTH]

            messages[msg_idx]["intent"] = {
                "intent": intent_names[0],
                "confidence": float(f"{probs[0]:.2f}"),
            }
            messages[msg_idx]["intent_ranking"] = [
                {"intent": name, "confidence": float(f"{score:.2f}")}
                for name, score in ranking
            ]

        return messages

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single message and return extracted intent information.
        
        Args:
            message: Input message dictionary with 'text' key
            
        Returns:
            Message with added 'intent' and 'intent_ranking' keys
        """
        if not message.get("text"):
            message["intent"] = {"intent": None, "confidence": 0.0}
            message["intent_ranking"] = []
            return message

        if not self.model:
            message["intent"] = {"intent": None, "confidence": 0.0}
            message["intent_ranking"] = []
            return message

        try:
            # Use batch prediction for single message
            result = self.predict_batch([message])
            return result[0]
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            message["intent"] = {"intent": None, "confidence": 0.0}
            message["intent_ranking"] = []
            return message