from typing import Any, Dict, List, Optional
import logging

from app.bot.nlu.pipeline import NLUComponent

logger = logging.getLogger(__name__)


class SpacyFeaturizer(NLUComponent):
    """Spacy featurizer component that processes text and adds spacy features.
    
    This component uses spaCy for tokenization and linguistic feature extraction.
    The spaCy model is lazy-loaded on first use to defer expensive model loading
    until actually needed during training or inference.
    
    Attributes:
        model_name: Name of the spaCy model to load (e.g., 'en_core_web_sm').
        _tokenizer: Cached spaCy language model instance (lazy-loaded).
    """

    def __init__(self, model_name: str = "en_core_web_sm") -> None:
        """Initialize the SpacyFeaturizer with a configurable model name.
        
        Args:
            model_name: Name of the spaCy model to load. Defaults to 'en_core_web_sm'.
                       The model will be loaded lazily on first use.
                       
        Raises:
            ValueError: If model_name is empty or None.
        """
        if not model_name or not isinstance(model_name, str):
            raise ValueError(
                f"model_name must be a non-empty string, got {model_name!r}"
            )
        
        self.model_name = model_name
        self._tokenizer: Optional[Any] = None

    def _load_model(self) -> None:
        """Lazy-load the spaCy model on first use.
        
        This method is called automatically on first access to ensure the
        expensive model loading operation is deferred until actually needed.
        
        Raises:
            OSError: If the spaCy model cannot be found or loaded.
            ImportError: If spaCy is not installed.
        """
        if self._tokenizer is not None:
            return
        
        try:
            import spacy
        except ImportError as e:
            logger.error(
                "spaCy is not installed. Install it with: pip install spacy"
            )
            raise ImportError(
                "spaCy library is required for SpacyFeaturizer. "
                "Install it with: pip install spacy"
            ) from e
        
        try:
            logger.info(f"Loading spaCy model: {self.model_name}")
            self._tokenizer = spacy.load(self.model_name)
            logger.info(f"Successfully loaded spaCy model: {self.model_name}")
        except OSError as e:
            logger.error(
                f"Failed to load spaCy model '{self.model_name}'. "
                f"Ensure the model is installed with: python -m spacy download {self.model_name}"
            )
            raise OSError(
                f"spaCy model '{self.model_name}' not found. "
                f"Install it with: python -m spacy download {self.model_name}"
            ) from e

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train the featurizer by processing training data with spaCy.
        
        Args:
            training_data: List of training examples, each containing at least a 'text' key.
            model_path: Directory path where trained model artifacts should be saved.
                       (Not used for spaCy featurizer as model is pre-trained)
        """
        self._load_model()
        
        for example in training_data:
            text = example.get("text", "").strip()
            if not text:
                continue
            
            try:
                example["spacy_doc"] = self._tokenizer(text)
            except Exception as e:
                logger.warning(
                    f"Failed to process text with spaCy model '{self.model_name}': {e}"
                )

    def load(self, model_path: str) -> bool:
        """Load the featurizer (no-op for spaCy as model is pre-trained).
        
        Args:
            model_path: Directory path containing saved model artifacts (unused).
            
        Returns:
            True, indicating successful initialization.
        """
        return True

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process text with spaCy and add doc to message.
        
        Args:
            message: Input message dictionary containing a 'text' key.
            
        Returns:
            The input message dictionary with 'spacy_doc' key added containing
            the processed spaCy Doc object.
        """
        if not message.get("text"):
            return message
        
        self._load_model()
        
        try:
            doc = self._tokenizer(message["text"])
            message["spacy_doc"] = doc
        except Exception as e:
            logger.error(
                f"Failed to process message with spaCy model '{self.model_name}': {e}"
            )
            raise
        
        return message