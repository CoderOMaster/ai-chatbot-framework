from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.bot.nlu.pipeline import NLUComponent


class SpacyModelFactory:
    """Factory that lazily loads spaCy models by their configured name."""

    def __init__(self) -> None:
        self._cache: Dict[str, "Language"] = {}

    def get(self, model_name: str) -> "Language":
        """Return a spaCy Language instance for the supplied model name."""
        if model_name not in self._cache:
            import spacy

            self._cache[model_name] = spacy.load(model_name)
        return self._cache[model_name]


SPACY_MODEL_FACTORY = SpacyModelFactory()


class SpacyFeaturizer(NLUComponent):
    """Spacy featurizer component that processes text and adds spacy features."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._tokenizer: Optional["Language"] = None

    def _get_tokenizer(self) -> "Language":
        """Return the spaCy tokenizer for the configured model name."""
        if self._tokenizer is None:
            self._tokenizer = SPACY_MODEL_FACTORY.get(self._model_name)
        return self._tokenizer

    def _process_text(self, text: str) -> Any:
        """Process a piece of text with the spaCy tokenizer."""
        return self._get_tokenizer()(text)

    def train(self, training_data: List[Dict[str, Any]], model_path: str) -> None:
        """Annotate training examples with spaCy docs."""
        for example in training_data:
            text = example.get("text", "").strip()
            if not text:
                continue
            example["spacy_doc"] = self._process_text(text)

    def load(self, model_path: str) -> bool:
        """Nothing to load for spacy featurizer."""
        return True

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process text with spaCy and add doc to message."""
        text = message.get("text", "")
        if not text:
            return message

        message["spacy_doc"] = self._process_text(text)
        return message