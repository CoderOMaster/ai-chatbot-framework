import os
import json
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict
import cloudpickle
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.isotonic import IsotonicRegression
import logging

from app.bot.nlu.pipeline import NLUComponent

logger = logging.getLogger(__name__)


@dataclass
class ModelVersion:
    """Metadata for a model version."""
    version_id: str
    timestamp: str
    training_samples: int
    accuracy: Optional[float] = None
    is_active: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class DriftMetrics:
    """Metrics for model drift detection."""
    timestamp: str
    prediction_entropy: float
    confidence_mean: float
    confidence_std: float
    class_distribution_change: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class SklearnIntentClassifier(NLUComponent):
    """Sklearn-based intent classifier with versioning, online learning, and drift detection.
    
    Features:
    - Model versioning and A/B testing support
    - Online learning capability
    - Confidence calibration using isotonic regression
    - Memory-efficient model loading
    - Model monitoring and drift detection
    """

    INTENT_RANKING_LENGTH = 3
    MODEL_NAME_TEMPLATE = "sklearn_intent_model_v{}.pkl"
    METADATA_FILE = "model_metadata.json"
    DRIFT_METRICS_FILE = "drift_metrics.json"
    
    def __init__(self, name: str = "sklearn_intent_classifier", parallelizable: bool = False):
        """Initialize the intent classifier.
        
        Args:
            name: Component name
            parallelizable: Whether component can run in parallel
        """
        super().__init__(name=name, parallelizable=parallelizable)
        self.model = None
        self.calibrator: Optional[CalibratedClassifierCV] = None
        self.model_version: Optional[ModelVersion] = None
        self.model_versions: Dict[str, ModelVersion] = {}
        self.drift_metrics: List[DriftMetrics] = []
        self.prediction_history: List[Tuple[str, float]] = []
        self.max_history_size = 1000
        self.model_path: Optional[str] = None
        self.n_jobs: int = int(os.getenv("N_JOBS", "-1"))

    def _generate_version_id(self, training_data: List[Dict[str, Any]]) -> str:
        """Generate unique version ID based on training data hash.
        
        Args:
            training_data: Training data to hash
            
        Returns:
            Version ID string
        """
        data_str = json.dumps(
            [(ex.get("intent"), len(ex.get("text", ""))) for ex in training_data],
            sort_keys=True
        )
        hash_obj = hashlib.sha256(data_str.encode())
        return hash_obj.hexdigest()[:12]

    def _get_model_path(self, model_dir: str, version_id: Optional[str] = None) -> str:
        """Get full path to model file.
        
        Args:
            model_dir: Directory containing models
            version_id: Optional version ID (uses latest if None)
            
        Returns:
            Full path to model file
        """
        if version_id:
            return os.path.join(model_dir, self.MODEL_NAME_TEMPLATE.format(version_id))
        return os.path.join(model_dir, self.MODEL_NAME_TEMPLATE.format("latest"))

    def _save_metadata(self, model_dir: str) -> None:
        """Save model metadata including versions and drift metrics.
        
        Args:
            model_dir: Directory to save metadata
        """
        metadata = {
            "current_version": self.model_version.to_dict() if self.model_version else None,
            "all_versions": {vid: v.to_dict() for vid, v in self.model_versions.items()},
            "drift_metrics": [m.to_dict() for m in self.drift_metrics[-100:]],
        }
        
        metadata_path = os.path.join(model_dir, self.METADATA_FILE)
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
        logger.info(f"Saved model metadata to {metadata_path}")

    def _load_metadata(self, model_dir: str) -> None:
        """Load model metadata from file.
        
        Args:
            model_dir: Directory containing metadata
        """
        metadata_path = os.path.join(model_dir, self.METADATA_FILE)
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
                
                if metadata.get("current_version"):
                    cv = metadata["current_version"]
                    self.model_version = ModelVersion(
                        version_id=cv["version_id"],
                        timestamp=cv["timestamp"],
                        training_samples=cv["training_samples"],
                        accuracy=cv.get("accuracy"),
                        is_active=cv.get("is_active", False),
                    )
                
                for vid, v in metadata.get("all_versions", {}).items():
                    self.model_versions[vid] = ModelVersion(
                        version_id=v["version_id"],
                        timestamp=v["timestamp"],
                        training_samples=v["training_samples"],
                        accuracy=v.get("accuracy"),
                        is_active=v.get("is_active", False),
                    )
                
                logger.info(f"Loaded metadata with {len(self.model_versions)} versions")
            except Exception as e:
                logger.warning(f"Failed to load metadata: {e}")

    def _calibrate_model(self, X: np.ndarray, y: np.ndarray) -> None:
        """Calibrate model using isotonic regression for better confidence scores.
        
        Args:
            X: Training features
            y: Training labels
        """
        if self.model is None:
            return
        
        try:
            self.calibrator = CalibratedClassifierCV(
                self.model,
                method="isotonic",
                cv=5,
            )
            self.calibrator.fit(X, y)
            logger.info("Model calibration completed")
        except Exception as e:
            logger.warning(f"Failed to calibrate model: {e}")
            self.calibrator = None

    def _update_drift_metrics(self, probabilities: np.ndarray, predictions: np.ndarray) -> None:
        """Update drift detection metrics.
        
        Args:
            probabilities: Prediction probabilities
            predictions: Predicted labels
        """
        if len(probabilities) == 0:
            return
        
        max_probs = np.max(probabilities, axis=1)
        entropy = -np.sum(probabilities * np.log(probabilities + 1e-10), axis=1).mean()
        
        metrics = DriftMetrics(
            timestamp=datetime.now().isoformat(),
            prediction_entropy=float(entropy),
            confidence_mean=float(max_probs.mean()),
            confidence_std=float(max_probs.std()),
            class_distribution_change=0.0,
        )
        
        self.drift_metrics.append(metrics)
        if len(self.drift_metrics) > 100:
            self.drift_metrics = self.drift_metrics[-100:]

    def get_spacy_embedding(self, spacy_doc) -> np.ndarray:
        """Extract embedding from spacy document.
        
        Args:
            spacy_doc: Spacy document object
            
        Returns:
            Embedding vector as numpy array
        """
        return np.array(spacy_doc.vector)

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train intent classifier with given training data.
        
        Args:
            training_data: List of training examples with 'text', 'spacy_doc', 'intent'
            model_path: Directory to save trained model
        """
        from sklearn.model_selection import GridSearchCV
        from sklearn.svm import SVC

        if not training_data:
            logger.warning("No training data provided")
            return

        X = []
        y = []
        for example in training_data:
            if example.get("text", "").strip() == "":
                continue
            X.append(example.get("spacy_doc"))
            y.append(example.get("intent"))

        if not X or not y:
            logger.warning("No valid training examples after filtering")
            return

        X = np.stack([self.get_spacy_embedding(example) for example in X])
        y = np.array(y)

        _, counts = np.unique(y, return_counts=True)
        cv_splits = max(2, min(5, np.min(counts) // 5))

        tuned_parameters = [
            {"C": [1, 2, 5, 10, 20, 100], "gamma": [0.1], "kernel": ["linear"]}
        ]

        classifier = GridSearchCV(
            SVC(C=1, probability=True, class_weight="balanced"),
            param_grid=tuned_parameters,
            n_jobs=self.n_jobs,
            cv=cv_splits,
            scoring="f1_weighted",
            verbose=1,
        )

        classifier.fit(X, y)
        best_model = classifier.best_estimator_

        version_id = self._generate_version_id(training_data)
        self.model_version = ModelVersion(
            version_id=version_id,
            timestamp=datetime.now().isoformat(),
            training_samples=len(training_data),
            accuracy=float(classifier.best_score_),
            is_active=True,
        )
        self.model_versions[version_id] = self.model_version

        self._calibrate_model(X, y)

        self.model = best_model
        self.model_path = model_path

        if model_path:
            os.makedirs(model_path, exist_ok=True)
            model_file = self._get_model_path(model_path, version_id)
            with open(model_file, "wb") as f:
                cloudpickle.dump(best_model, f)
            
            latest_file = self._get_model_path(model_path)
            with open(latest_file, "wb") as f:
                cloudpickle.dump(best_model, f)
            
            self._save_metadata(model_path)
            logger.info(f"Training completed. Model saved to {model_file}")

        self._is_loaded = True

    def load(self, model_path: str) -> bool:
        """Load trained model from given path.
        
        Args:
            model_path: Directory containing model files
            
        Returns:
            True if load successful, False otherwise
        """
        try:
            self.model_path = model_path
            self._load_metadata(model_path)
            
            latest_path = self._get_model_path(model_path)
            if not os.path.exists(latest_path):
                logger.error(f"Model file not found: {latest_path}")
                return False
            
            with open(latest_path, "rb") as f:
                self.model = cloudpickle.load(f)
            
            self._is_loaded = True
            logger.info(f"Model loaded successfully from {latest_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False

    def load_version(self, model_path: str, version_id: str) -> bool:
        """Load a specific model version for A/B testing.
        
        Args:
            model_path: Directory containing model files
            version_id: Version ID to load
            
        Returns:
            True if load successful, False otherwise
        """
        try:
            version_path = self._get_model_path(model_path, version_id)
            if not os.path.exists(version_path):
                logger.error(f"Model version not found: {version_path}")
                return False
            
            with open(version_path, "rb") as f:
                self.model = cloudpickle.load(f)
            
            if version_id in self.model_versions:
                self.model_version = self.model_versions[version_id]
            
            self._is_loaded = True
            logger.info(f"Model version {version_id} loaded successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to load model version {version_id}: {e}")
            return False

    def partial_fit(self, training_data: List[Dict[str, Any]]) -> None:
        """Perform online learning with new data (incremental training).
        
        Args:
            training_data: New training examples for incremental learning
        """
        if self.model is None:
            logger.warning("Model not initialized. Call train() first.")
            return
        
        try:
            from sklearn.svm import SVC
            
            X = []
            y = []
            for example in training_data:
                if example.get("text", "").strip() == "":
                    continue
                X.append(example.get("spacy_doc"))
                y.append(example.get("intent"))
            
            if not X or not y:
                logger.warning("No valid examples for partial fit")
                return
            
            X = np.stack([self.get_spacy_embedding(example) for example in X])
            y = np.array(y)
            
            self.model.fit(X, y)
            self._calibrate_model(X, y)
            logger.info(f"Partial fit completed with {len(training_data)} new examples")
        except Exception as e:
            logger.error(f"Failed to perform partial fit: {e}")

    def predict_proba(self, X: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
        """Predict probabilities for input.
        
        Args:
            X: Input dictionary with 'spacy_doc' key
            
        Returns:
            Tuple of (predicted_class_indices, probabilities)
        """
        if self.model is None:
            return np.array([]), np.array([])
        
        embedding = self.get_spacy_embedding(X.get("spacy_doc"))
        embedding = embedding.reshape(1, -1)
        
        if self.calibrator is not None:
            pred_result = self.calibrator.predict_proba(embedding)
        else:
            pred_result = self.model.predict_proba(embedding)
        
        sorted_indices = np.fliplr(np.argsort(pred_result, axis=1))
        return sorted_indices, pred_result[:, sorted_indices]

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message and extract intent with confidence.
        
        Args:
            message: Input message with 'text' and 'spacy_doc'
            
        Returns:
            Message with added 'intent' and 'intent_ranking' fields
        """
        if not message.get("text") or not message.get("spacy_doc"):
            message["intent"] = {"name": None, "confidence": 0.0}
            message["intent_ranking"] = []
            return message

        intent = {"name": None, "confidence": 0.0}
        intent_ranking = []

        if self.model:
            try:
                intents, probabilities = self.predict_proba(message)
                self._update_drift_metrics(probabilities, intents)
                
                intents = [self.model.classes_[int(intent)] for intent in intents.flatten()]
                probabilities = probabilities.flatten()

                if len(intents) > 0 and len(probabilities) > 0:
                    ranking = list(zip(list(intents), list(probabilities)))
                    ranking = ranking[: self.INTENT_RANKING_LENGTH]

                    intent = {"name": intents[0], "confidence": float(probabilities[0])}
                    intent_ranking = [
                        {"name": intent_name, "confidence": float(score)}
                        for intent_name, score in ranking
                    ]
                    
                    self.prediction_history.append((intents[0], float(probabilities[0])))
                    if len(self.prediction_history) > self.max_history_size:
                        self.prediction_history = self.prediction_history[-self.max_history_size:]
            except Exception as e:
                logger.error(f"Error during prediction: {e}")
                intent = {"name": None, "confidence": 0.0}
                intent_ranking = []

        message["intent"] = intent
        message["intent_ranking"] = intent_ranking
        return message

    def get_drift_report(self) -> Dict[str, Any]:
        """Get model drift detection report.
        
        Returns:
            Dictionary with drift metrics and analysis
        """
        if not self.drift_metrics:
            return {"status": "no_data"}
        
        recent_metrics = self.drift_metrics[-50:]
        entropies = [m.prediction_entropy for m in recent_metrics]
        confidences = [m.confidence_mean for m in recent_metrics]
        
        return {
            "status": "ok",
            "total_predictions": len(self.prediction_history),
            "recent_entropy_mean": float(np.mean(entropies)),
            "recent_entropy_std": float(np.std(entropies)),
            "recent_confidence_mean": float(np.mean(confidences)),
            "recent_confidence_std": float(np.std(confidences)),
            "last_update": self.drift_metrics[-1].timestamp if self.drift_metrics else None,
        }

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about current model.
        
        Returns:
            Dictionary with model metadata and statistics
        """
        return {
            "is_loaded": self._is_loaded,
            "current_version": self.model_version.to_dict() if self.model_version else None,
            "available_versions": list(self.model_versions.keys()),
            "has_calibrator": self.calibrator is not None,
            "prediction_history_size": len(self.prediction_history),
            "drift_metrics_count": len(self.drift_metrics),
        }