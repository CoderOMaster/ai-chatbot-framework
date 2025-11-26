import logging
from typing import Dict, Any, Optional
from types import MappingProxyType
from app.bot.nlu.pipeline import NLUComponent

logger = logging.getLogger(__name__)


class SynonymReplacer(NLUComponent):
    """
    Replaces extracted entity values with their root words
    using an immutable synonyms dictionary.
    
    The synonyms dictionary is injected at initialization and cannot be modified
    after instantiation, ensuring thread-safe operation across multiple NLU
    configurations and microservices.
    """

    def __init__(self, synonyms: Optional[Dict[str, str]] = None) -> None:
        """Initialize SynonymReplacer with immutable synonyms mapping.
        
        Args:
            synonyms: Dictionary mapping synonym values (lowercase) to their root words.
                     If None, an empty immutable mapping is used.
                     The dictionary is converted to a MappingProxyType to prevent
                     accidental modifications after initialization.
        """
        # Convert to lowercase keys for case-insensitive matching
        normalized_synonyms = {k.lower(): v for k, v in (synonyms or {}).items()}
        # Make immutable to prevent runtime modifications
        self._synonyms: MappingProxyType = MappingProxyType(normalized_synonyms)

    @property
    def synonyms(self) -> MappingProxyType:
        """Get the immutable synonyms mapping.
        
        Returns:
            MappingProxyType: Read-only view of the synonyms dictionary.
        """
        return self._synonyms

    def replace_synonyms(self, entities: Dict[str, str]) -> Dict[str, str]:
        """Replace extracted entity values with root words by matching with synonyms dict.
        
        Args:
            entities: Dictionary of entity name to entity value mappings.
            
        Returns:
            Dictionary with replaced entity values where applicable.
        """
        for entity in entities.keys():
            entity_value = str(entities[entity]).lower()
            if entity_value in self._synonyms:
                entities[entity] = self._synonyms[entity_value]
        return entities

    def train(self, training_data: Dict[str, Any], model_path: str) -> None:
        """Nothing to train for synonym replacement.
        
        Args:
            training_data: Training data (unused for this stateless component).
            model_path: Model path (unused for this stateless component).
        """
        pass

    def load(self, model_path: str) -> bool:
        """Nothing to load for synonym replacement.
        
        Args:
            model_path: Model path (unused for this stateless component).
            
        Returns:
            True: This stateless component always loads successfully.
        """
        return True

    def process(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message by replacing entity values with their synonyms.
        
        Args:
            message: Input message dictionary containing optional 'entities' key.
            
        Returns:
            Processed message with entity values replaced where synonyms exist.
        """
        if not message.get("entities"):
            return message

        entities = message["entities"]
        message["entities"] = self.replace_synonyms(entities)
        return message