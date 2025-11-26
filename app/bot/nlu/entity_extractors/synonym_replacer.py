import logging
from typing import Any, Dict, List, Optional, Union

from app.bot.nlu.pipeline import (
    NLUComponent,
    MessageDict,
    Entity,
    TrainingData,
    ModelPath,
)

logger = logging.getLogger(__name__)


class SynonymReplacer(NLUComponent):
    """
    Replaces extracted entity values with their canonical form using a provided
    synonyms mapping.

    Notes:
    - The synonyms mapping SHOULD be provided by the pipeline loader (e.g.
      pipeline_utils) and passed into this component's constructor. This keeps
      the component pure and easy to test.
    - The component supports two legacy shapes for `message["entities"]`:
      * List[Entity] (preferred, see app.bot.nlu.pipeline.Entity)
      * Dict[str, str] mapping entity name -> value
    """

    def __init__(self, synonyms: Optional[Dict[str, str]] = None) -> None:
        """Create a SynonymReplacer.

        Args:
            synonyms: Mapping of synonym (any-case) -> canonical value. Keys are
                normalized to lowercase internally. If None, an empty mapping
                is used.
        """
        # Normalize keys to lowercase to allow case-insensitive matching
        self.synonyms: Dict[str, str] = {k.lower(): v for k, v in (synonyms or {}).items()}

    def replace_synonyms_in_list(self, entities: List[Entity]) -> List[Entity]:
        """Replace values inside a list of Entity typed dicts in-place and
        return the same list for convenience.

        Args:
            entities: list of Entity objects as produced by earlier NLU components.
        Returns:
            The same list with entity['value'] replaced where a synonym match was found.
        """
        for ent in entities:
            if not isinstance(ent, dict):
                continue
            value = str(ent.get("value", ""))
            canonical = self.synonyms.get(value.lower())
            if canonical is not None:
                ent["value"] = canonical
        return entities

    def replace_synonyms_in_mapping(self, entities: Dict[str, str]) -> Dict[str, str]:
        """Replace values inside a mapping of entity name -> value.

        This preserves backward compatibility with older components that provided
        entities as a simple mapping.
        """
        for name, val in list(entities.items()):
            value = str(val)
            canonical = self.synonyms.get(value.lower())
            if canonical is not None:
                entities[name] = canonical
        return entities

    def replace_synonyms(self, entities: Union[List[Entity], Dict[str, str]]) -> Union[List[Entity], Dict[str, str]]:
        """Dispatch to the appropriate replacement routine based on the entities shape."""
        if isinstance(entities, list):
            return self.replace_synonyms_in_list(entities)
        if isinstance(entities, dict):
            return self.replace_synonyms_in_mapping(entities)
        # Unknown shape - return as-is
        logger.debug("SynonymReplacer received unsupported entities type: %s", type(entities))
        return entities

    def train(self, training_data: TrainingData, model_path: ModelPath) -> None:
        """No training required for synonym replacement component."""
        return None

    def load(self, model_path: ModelPath) -> bool:
        """Nothing to load for synonym replacement; component is configuration-only."""
        return True

    def process(self, message: MessageDict) -> MessageDict:
        """Process a message by replacing entity values with their synonyms.

        The component updates message["entities"] in place and returns the
        message for pipeline convenience.
        """
        if not message.get("entities"):
            return message

        message["entities"] = self.replace_synonyms(message["entities"])
        return message