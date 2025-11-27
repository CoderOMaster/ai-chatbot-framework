from typing import Any, Dict, List, Optional
import logging

from pydantic import BaseSettings

from app.bot.nlu.pipeline import NLUComponent

logger = logging.getLogger(__name__)

# Cache loaded spaCy pipelines per process to avoid repeated heavy loads
_SPACY_PIPELINE_CACHE: Dict[str, Any] = {}


class SpacyFeaturizerConfig(BaseSettings):
    """Configuration for SpacyFeaturizer.

    model_name: Name of the spaCy model to load. This can be set via
    environment variables when using BaseSettings (e.g. SPACYFEATURIZER_MODEL_NAME).
    """

    model_name: str = "en_core_web_sm"


def _get_spacy_nlp(model_name: str) -> Any:
    """Return a cached spaCy nlp pipeline for the given model_name or load it.

    Args:
        model_name: The spaCy model name to load (e.g. 'en_core_web_sm').

    Returns:
        The loaded spaCy Language pipeline instance.

    Raises:
        RuntimeError: If spaCy is not installed or the model cannot be loaded.
    """
    if model_name in _SPACY_PIPELINE_CACHE:
        return _SPACY_PIPELINE_CACHE[model_name]

    try:
        import spacy  # local import to keep module import lightweight

        nlp = spacy.load(model_name)
        _SPACY_PIPELINE_CACHE[model_name] = nlp
        logger.info("Loaded spaCy model '%s' into cache", model_name)
        return nlp
    except Exception as exc:  # broad catch to surface helpful message
        logger.exception("Failed to load spaCy model '%s'", model_name)
        raise RuntimeError(f"Failed to load spaCy model '{model_name}': {exc}") from exc


class SpacyFeaturizer(NLUComponent):
    """spaCy featurizer component that processes text and attaches a spaCy Doc.

    The spaCy pipeline is loaded lazily on first use and pipelines are cached
    per process to avoid repeated weight loads during multiple training runs.

    This component accepts either a raw model_name string or a
    SpacyFeaturizerConfig instance for configuration. Backwards compatible
    usage: SpacyFeaturizer("en_core_web_sm").
    """

    def __init__(self, model_name_or_config: Optional[Any] = None) -> None:
        """Initialize the featurizer without immediately loading the spaCy model.

        Args:
            model_name_or_config: Either a model name string or a
                SpacyFeaturizerConfig. If omitted, defaults from
                SpacyFeaturizerConfig are used.
        """
        if isinstance(model_name_or_config, SpacyFeaturizerConfig):
            self.config = model_name_or_config
        elif isinstance(model_name_or_config, str):
            self.config = SpacyFeaturizerConfig(model_name=model_name_or_config)
        else:
            self.config = SpacyFeaturizerConfig()

        # _nlp holds the actual spaCy pipeline instance after lazy load
        self._nlp: Optional[Any] = None

    def _ensure_nlp(self) -> Any:
        """Ensure the spaCy pipeline is loaded and return it."""
        if self._nlp is None:
            self._nlp = _get_spacy_nlp(self.config.model_name)
        return self._nlp

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Process training examples with spaCy to attach Doc objects.

        The spaCy model is loaded lazily on first training call. Empty texts
        are skipped.
        """
        nlp = self._ensure_nlp()

        for example in training_data:
            text = example.get("text", "")
            if not isinstance(text, str) or text.strip() == "":
                continue
            example["spacy_doc"] = nlp(text)

    def load(self, model_path: str) -> bool:
        """No on-disk artifacts to load for this component; ensure model is available.

        Returns True when the configured spaCy model can be loaded (or is cached).
        """
        try:
            self._ensure_nlp()
            return True
        except RuntimeError:
            return False

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process an incoming message with spaCy and attach the Doc as 'spacy_doc'.

        If message has no 'text' key or text is falsy, the message is returned
        unchanged.
        """
        text = message.get("text")
        if not text:
            return message

        nlp = self._ensure_nlp()
        message["spacy_doc"] = nlp(text)
        return message