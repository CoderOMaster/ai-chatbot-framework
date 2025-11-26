from typing import Any, Dict, List, Optional

from app.bot.nlu.pipeline import NLUComponent, TrainingData, MessageDict, ModelPath


# Per-process cache for loaded spaCy models. Models are loaded lazily by
# get_spacy_model to avoid heavy import-time work and to allow centralized
# control over model instantiation (helpful for microservices and testing).
_model_cache: Dict[str, Any] = {}


def get_spacy_model(model_name: str, **load_kwargs: Any) -> Any:
    """Return a spaCy language model for the given name, caching it per process.

    The spaCy package is imported lazily when this function is first called so
    that importing this module does not trigger a costly model load.

    Args:
        model_name: Name or path of the spaCy model to load (e.g. "en_core_web_sm").
        **load_kwargs: Passed through to spacy.load.

    Returns:
        The loaded spaCy Language object.

    Raises:
        RuntimeError: If spaCy is not installed.
    """
    if model_name in _model_cache:
        return _model_cache[model_name]

    try:
        import spacy  # imported lazily
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "spaCy is required for SpacyFeaturizer but is not installed"
        ) from exc

    nlp = spacy.load(model_name, **load_kwargs)
    _model_cache[model_name] = nlp
    return nlp


class SpacyFeaturizer(NLUComponent):
    """SpaCy-based featurizer for NLU pipeline.

    This component defers loading the spaCy model until it's actually required
    (first call to train or process) by using the get_spacy_model factory. This
    keeps imports cheap and centralizes model instantiation and caching so a
    single model instance can be shared per process.
    """

    def __init__(self, model_name: str) -> None:
        """Create a featurizer that will use the given spaCy model name.

        The model is not loaded at construction time to avoid heavy startup
        costs during module import. It will be loaded lazily on demand.
        """
        self.model_name = model_name
        self._nlp: Optional[Any] = None

    def _ensure_model(self) -> Any:
        """Ensure the spaCy model is loaded and return it."""
        if self._nlp is None:
            self._nlp = get_spacy_model(self.model_name)
        return self._nlp

    def train(self, training_data: TrainingData, model_path: ModelPath) -> None:
        """Process training examples and attach a spaCy Doc under the key "spacy_doc".

        Empty or whitespace-only texts are skipped.
        """
        nlp = self._ensure_model()
        for example in training_data:
            text = example.get("text", "")
            if not text or text.strip() == "":
                continue
            example["spacy_doc"] = nlp(text)

    def load(self, model_path: ModelPath) -> bool:
        """No on-disk artifacts to load for this component; model is provided
        by the centralized factory when needed.
        """
        return True

    def process(self, message: MessageDict) -> MessageDict:
        """Process an incoming message with spaCy and attach the Doc to it.

        If the message has no text key or an empty text value it is returned
        unchanged.
        """
        text = message.get("text")
        if not text:
            return message

        nlp = self._ensure_model()
        message["spacy_doc"] = nlp(text)
        return message