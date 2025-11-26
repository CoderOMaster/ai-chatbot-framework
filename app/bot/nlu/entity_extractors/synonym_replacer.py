import logging
from typing import Dict, Any, Optional
from shared.nlu.pipeline import NLUComponent

logger = logging.getLogger(__name__)


class SynonymReplacer(NLUComponent):
    """
    Replaces extracted entity values with their root words
    using a predefined synonyms dictionary.
    """

    def __init__(self, synonyms: Optional[Dict[str, str]] = None):
        """
        Initialize the SynonymReplacer with an optional synonyms mapping.
        
        :param synonyms: Dictionary mapping entity values to their root words
        :raises TypeError: If synonyms is not a dict or None
        """
        if synonyms is not None and not isinstance(synonyms, dict):
            raise TypeError(f"synonyms must be a dict or None, got {type(synonyms)}")
        self.synonyms = synonyms or {}

    def replace_synonyms(self, entities: Dict[str, str]) -> Dict[str, str]:
        """
        Replace extracted entity values with root words by matching with synonyms dict.
        
        :param entities: Dictionary of entity name to entity value mappings
        :return: Dictionary with replaced entity values where applicable
        :raises TypeError: If entities is not a dict
        """
        if not isinstance(entities, dict):
            raise TypeError(f"entities must be a dict, got {type(entities)}")
        
        for entity in entities.keys():
            entity_value = str(entities[entity])
            if entity_value.lower() in self.synonyms:
                entities[entity] = self.synonyms[entity_value.lower()]
        return entities

    def train(self, training_data: Dict[str, Any], model_path: str) -> None:
        """Nothing to train for synonym replacement."""
        pass

    def load(self, model_path: str) -> bool:
        """Nothing to load for synonym replacement."""
        return True

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a message by replacing entity values with their synonyms.
        
        :param message: Message dictionary containing entities
        :return: Processed message with replaced entity values
        :raises TypeError: If message is not a dict
        """
        if not isinstance(message, dict):
            raise TypeError(f"message must be a dict, got {type(message)}")
        
        if not message.get("entities"):
            return message

        entities = message["entities"]
        message["entities"] = self.replace_synonyms(entities)
        return message