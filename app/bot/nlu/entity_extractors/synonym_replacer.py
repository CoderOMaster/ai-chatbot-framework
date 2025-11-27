import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Dict, Any, Optional, Mapping

from app.bot.nlu.pipeline import NLUComponent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SynonymMap:
    """Immutable container for synonyms.

    Normalizes all keys to lower-case on construction and exposes an
    immutable MappingProxyType to prevent accidental mutation.
    """

    synonyms: Mapping[str, str]

    def __post_init__(self) -> None:
        normalized = {str(k).lower(): v for k, v in dict(self.synonyms or {}).items()}
        # Replace with an immutable mapping
        object.__setattr__(self, "synonyms", MappingProxyType(normalized))

    def get(self, value: str) -> Optional[str]:
        """Return the canonical synonym for a value (case-insensitive), or None.

        Args:
            value: The entity value to look up.
        """
        if value is None:
            return None
        return self.synonyms.get(value.lower())


class SynonymReplacer(NLUComponent):
    """
    Replaces extracted entity values with their canonical root words using a
    predefined, immutable SynonymMap.

    Characteristics:
    - Entity keys are normalized to lower-case in the returned mapping.
    - Synonym dictionaries are stored immutably in SynonymMap instances.
    - replace_synonyms returns a new dict so downstream code cannot mutate
      this component's internal state by accident.
    """

    def __init__(self, synonyms: Optional[Dict[str, str]] = None) -> None:
        """Create a SynonymReplacer.

        Args:
            synonyms: Optional mapping of synonym -> canonical form. Keys are
                normalized to lower-case internally.
        """
        self._synonym_map = SynonymMap(synonyms or {})

    def configure(self, synonyms: Optional[Dict[str, str]] = None) -> None:
        """Update the synonyms at runtime by replacing the underlying map.

        This method intentionally replaces the whole SynonymMap with a new
        immutable instance to avoid in-place mutation.
        """
        logger.info("Configuring SynonymReplacer with %s synonyms", len(synonyms or {}))
        self._synonym_map = SynonymMap(synonyms or {})

    def replace_synonyms(self, entities: Dict[str, Any]) -> Dict[str, Any]:
        """Return a new entity mapping with normalized keys and synonym-replaced values.

        Args:
            entities: Mapping of entity name -> extracted value.

        Returns:
            A new dict with all entity keys normalized to lower-case and any
            string values replaced by their canonical synonym where applicable.
        """
        if not entities:
            return {}

        new_entities: Dict[str, Any] = {}
        for key, value in entities.items():
            norm_key = str(key).lower()
            # Only perform synonym lookup on string-like values
            if isinstance(value, str):
                replacement = self._synonym_map.get(value)
                new_entities[norm_key] = replacement if replacement is not None else value
            else:
                new_entities[norm_key] = value

        return new_entities

    def train(self, training_data: Dict[str, Any], model_path: str) -> None:
        """No-op for synonym replacement component."""
        return None

    def load(self, model_path: str) -> bool:
        """No-op load; nothing persisted for this lightweight component."""
        return True

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message by replacing entity values with their canonical forms.

        The returned message is a shallow copy of the input with the
        'entities' mapping replaced by a new dict produced by replace_synonyms,
        ensuring downstream components cannot mutate this component's internal
        state via shared references.
        """
        if not message.get("entities"):
            # Return the message unchanged (pipeline already works with copies)
            return message

        entities = message["entities"]
        replaced = self.replace_synonyms(entities)

        new_message = dict(message)
        new_message["entities"] = replaced
        return new_message