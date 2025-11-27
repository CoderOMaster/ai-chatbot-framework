import logging
import os
import threading
from functools import lru_cache
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

from app.bot.nlu.pipeline import NLUComponent

logger = logging.getLogger(__name__)


class SpacyModelSingleton:
    """Singleton wrapper for spaCy model with lazy loading and warming."""

    _instance: Optional["SpacyModelSingleton"] = None
    _lock = threading.Lock()
    _model_cache: Dict[str, Any] = {}

    def __new__(cls, model_name: str = "en_core_web_sm") -> "SpacyModelSingleton":
        """Ensure only one instance of SpacyModelSingleton exists.
        
        Args:
            model_name: Name of the spaCy model to load
            
        Returns:
            Singleton instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, model_name: str = "en_core_web_sm") -> None:
        """Initialize the singleton with spaCy model.
        
        Args:
            model_name: Name of the spaCy model to load
        """
        if self._initialized:
            return

        self.model_name = model_name
        self.nlp = None
        self._doc_cache: Dict[str, Any] = {}
        self._cache_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._initialized = True

    def _download_model(self) -> None:
        """Download spaCy model if not already present."""
        try:
            import spacy
            
            try:
                spacy.load(self.model_name)
                logger.info(f"spaCy model '{self.model_name}' already present")
            except OSError:
                logger.info(f"Downloading spaCy model '{self.model_name}'...")
                import subprocess
                import sys
                
                subprocess.check_call(
                    [sys.executable, "-m", "spacy", "download", self.model_name]
                )
                logger.info(f"Successfully downloaded spaCy model '{self.model_name}'")
        except Exception as e:
            logger.error(f"Failed to download spaCy model: {e}")
            raise

    def load(self) -> None:
        """Load the spaCy model into memory."""
        if self.nlp is not None:
            logger.debug(f"spaCy model '{self.model_name}' already loaded")
            return

        try:
            self._download_model()
            import spacy
            
            self.nlp = spacy.load(self.model_name)
            logger.info(f"Loaded spaCy model '{self.model_name}'")
            self._warm_model()
        except Exception as e:
            logger.error(f"Failed to load spaCy model '{self.model_name}': {e}")
            raise

    def _warm_model(self) -> None:
        """Warm up the model by processing sample texts."""
        sample_texts = [
            "Hello world",
            "This is a test",
            "Natural language processing",
            "Machine learning models",
        ]
        
        try:
            for text in sample_texts:
                _ = self.nlp(text)
            logger.info(f"Model warming completed for '{self.model_name}'")
        except Exception as e:
            logger.warning(f"Model warming failed: {e}")

    def is_healthy(self) -> bool:
        """Check if model is loaded and functional.
        
        Returns:
            True if model is healthy, False otherwise
        """
        if self.nlp is None:
            return False
        
        try:
            _ = self.nlp("health check")
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    @lru_cache(maxsize=1024)
    def _get_cache_key(self, text: str) -> str:
        """Generate cache key for text (using hash for memory efficiency).
        
        Args:
            text: Input text
            
        Returns:
            Cache key
        """
        return str(hash(text))

    def process(self, text: str, use_cache: bool = True) -> Any:
        """Process text with spaCy model with optional caching.
        
        Args:
            text: Input text to process
            use_cache: Whether to use cached results
            
        Returns:
            Processed spaCy Doc object
            
        Raises:
            RuntimeError: If model is not loaded
        """
        if self.nlp is None:
            raise RuntimeError("spaCy model not loaded. Call load() first.")

        if use_cache:
            cache_key = self._get_cache_key(text)
            with self._cache_lock:
                if cache_key in self._doc_cache:
                    logger.debug(f"Cache hit for text: {text[:50]}...")
                    return self._doc_cache[cache_key]

        doc = self.nlp(text)

        if use_cache:
            with self._cache_lock:
                self._doc_cache[cache_key] = doc

        return doc

    def process_batch(self, texts: List[str], use_cache: bool = True) -> List[Any]:
        """Process multiple texts concurrently.
        
        Args:
            texts: List of texts to process
            use_cache: Whether to use cached results
            
        Returns:
            List of processed spaCy Doc objects
        """
        if self.nlp is None:
            raise RuntimeError("spaCy model not loaded. Call load() first.")

        results = []
        futures = [
            self._executor.submit(self.process, text, use_cache) for text in texts
        ]

        for future in futures:
            try:
                results.append(future.result())
            except Exception as e:
                logger.error(f"Error processing text in batch: {e}")
                raise

        return results

    def clear_cache(self) -> None:
        """Clear the document cache."""
        with self._cache_lock:
            self._doc_cache.clear()
        logger.info("Document cache cleared")

    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        with self._cache_lock:
            return {
                "cache_size": len(self._doc_cache),
                "max_cache_size": 1024,
            }


class SpacyFeaturizer(NLUComponent):
    """Spacy featurizer component that processes text and adds spacy features.
    
    Uses a singleton spaCy model with caching and concurrent processing support.
    """

    def __init__(
        self,
        model_name: str = "en_core_web_sm",
        use_cache: bool = True,
        parallelizable: bool = True,
    ):
        """Initialize SpacyFeaturizer.
        
        Args:
            model_name: Name of the spaCy model to use
            use_cache: Whether to cache tokenized documents
            parallelizable: Whether this component can run in parallel
        """
        super().__init__(name="spacy_featurizer", parallelizable=parallelizable)
        self.model_name = model_name
        self.use_cache = use_cache
        self._model: Optional[SpacyModelSingleton] = None

    def _get_model(self) -> SpacyModelSingleton:
        """Get or create the singleton model instance.
        
        Returns:
            SpacyModelSingleton instance
        """
        if self._model is None:
            self._model = SpacyModelSingleton(self.model_name)
        return self._model

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Train the featurizer by processing training data.
        
        Args:
            training_data: List of training examples
            model_path: Path to save trained model (unused for spaCy)
        """
        model = self._get_model()
        if not model.is_healthy():
            model.load()

        for example in training_data:
            if example.get("text", "").strip() == "":
                continue
            try:
                example["spacy_doc"] = model.process(
                    example["text"], use_cache=self.use_cache
                )
            except Exception as e:
                logger.error(f"Error processing training example: {e}")
                raise

        logger.info(f"Trained spacy featurizer with {len(training_data)} examples")

    def load(self, model_path: str) -> bool:
        """Load the spaCy model.
        
        Args:
            model_path: Path to load model from (unused for spaCy)
            
        Returns:
            True if load successful, False otherwise
        """
        try:
            model = self._get_model()
            model.load()
            self._is_loaded = True
            logger.info("SpacyFeaturizer loaded successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to load SpacyFeaturizer: {e}")
            return False

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process text with spacy and add doc to message.
        
        Args:
            message: Input message with 'text' field
            
        Returns:
            Message with added 'spacy_doc' field
        """
        if not message.get("text"):
            return message

        try:
            model = self._get_model()
            if not model.is_healthy():
                model.load()

            doc = model.process(message["text"], use_cache=self.use_cache)
            message["spacy_doc"] = doc
            return message
        except Exception as e:
            logger.error(f"Error processing message with spacy: {e}")
            raise

    def health_check(self) -> Dict[str, Any]:
        """Perform health check on the featurizer.
        
        Returns:
            Dictionary with health status and metrics
        """
        model = self._get_model()
        is_healthy = model.is_healthy()
        cache_stats = model.get_cache_stats() if is_healthy else {}

        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "model_name": self.model_name,
            "model_loaded": model.nlp is not None,
            "cache_stats": cache_stats,
        }