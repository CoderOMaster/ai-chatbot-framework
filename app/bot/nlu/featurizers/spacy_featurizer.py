import os
from typing import Any, Dict, List, Optional
from shared.nlu.pipeline import NLUComponent


class SpacyFeaturizer(NLUComponent):
    """Spacy featurizer component that processes text and adds spacy features.
    
    Features:
    - Lazy loading of spaCy model to avoid cold-start delays
    - Configurable model name via SPACY_MODEL_NAME environment variable
    - Health check support for microservice deployment
    - Error handling for model loading failures
    """

    def __init__(self, model_name: Optional[str] = None):
        """Initialize SpacyFeaturizer with optional model name.
        
        Args:
            model_name: Name of spaCy model to load. If not provided, uses
                       SPACY_MODEL_NAME environment variable (defaults to 'en_core_web_sm').
        
        Raises:
            ValueError: If model_name is not provided and SPACY_MODEL_NAME env var is not set.
        """
        self.model_name = model_name or os.getenv("SPACY_MODEL_NAME", "en_core_web_sm")
        self._tokenizer: Optional[Any] = None
        self._model_load_error: Optional[Exception] = None

    @property
    def tokenizer(self) -> Any:
        """Lazy load spaCy model on first access.
        
        Returns:
            Loaded spaCy language model.
        
        Raises:
            RuntimeError: If model loading fails.
        """
        if self._tokenizer is None:
            try:
                import spacy
                self._tokenizer = spacy.load(self.model_name)
            except Exception as e:
                self._model_load_error = e
                raise RuntimeError(
                    f"Failed to load spaCy model '{self.model_name}': {str(e)}"
                ) from e
        return self._tokenizer

    def health_check(self) -> Dict[str, Any]:
        """Health check endpoint for microservice deployment.
        
        Returns:
            Dictionary with health status and model information.
        """
        status = "healthy"
        details = {
            "model_name": self.model_name,
            "model_loaded": self._tokenizer is not None,
        }

        if self._model_load_error:
            status = "unhealthy"
            details["error"] = str(self._model_load_error)

        return {
            "status": status,
            "component": "spacy_featurizer",
            "details": details,
        }

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train on training data by processing text with spaCy.
        
        Args:
            training_data: List of training examples with 'text' field.
            model_path: Path to save model (not used for spaCy featurizer).
        """
        for example in training_data:
            if example.get("text", "").strip() == "":
                continue
            try:
                example["spacy_doc"] = self.tokenizer(example["text"])
            except Exception as e:
                raise RuntimeError(
                    f"Failed to process training example: {str(e)}"
                ) from e

    def load(self, model_path: str) -> bool:
        """Load model state (no-op for spaCy featurizer).
        
        Args:
            model_path: Path to model directory (unused).
        
        Returns:
            True to indicate successful load.
        """
        return True

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process text with spaCy and add doc to message.
        
        Args:
            message: Message dictionary with 'text' field.
        
        Returns:
            Message dictionary with 'spacy_doc' field added.
        
        Raises:
            RuntimeError: If spaCy model fails to process text.
        """
        if not message.get("text"):
            return message

        try:
            doc = self.tokenizer(message["text"])
            message["spacy_doc"] = doc
        except Exception as e:
            raise RuntimeError(
                f"Failed to process message text: {str(e)}"
            ) from e

        return message