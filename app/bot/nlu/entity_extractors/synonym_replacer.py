import logging
from typing import Dict, Any, Mapping

from app.bot.nlu.pipeline import NLUComponent

logger = logging.getLogger(__name__)


Entities = Dict[str, str]


class SynonymReplacer(NLUComponent):
    """
    Replaces extracted entity values with their root words
    using a predefined synonyms dictionary.
    """

    def __init__(self, synonyms: Mapping[str, str]) -> None:
        """Init the replacer with a synonyms map that has already been loaded."""
        self.synonyms = {key.lower(): value for key, value in synonyms.items()}

    def replace_synonyms(self, entities: Entities) -> Entities:
        """Replace extracted entity values with root words by matching with the synonyms map."""
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
        """Process a message by replacing entity values with their synonyms."""
        if not message.get("entities"):
            return message

        entities = message["entities"]
        message["entities"] = self.replace_synonyms(entities)
        return message