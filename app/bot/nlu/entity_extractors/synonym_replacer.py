import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ReplacementMetrics:
    """Metrics for synonym replacement operations."""
    total_replacements: int = 0
    replacement_hits: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "total_replacements": self.total_replacements,
            "replacement_hits": self.replacement_hits,
            "timestamp": self.timestamp.isoformat(),
        }


class SynonymReplacer:
    """
    Pure function-based synonym replacer for entity values.
    Replaces extracted entity values with their root words using a synonyms dictionary.
    """

    def __init__(self, synonyms: Optional[Dict[str, str]] = None):
        """Initialize synonym replacer with optional synonyms dictionary.
        
        Args:
            synonyms: Dictionary mapping synonym values to root words
            
        Raises:
            TypeError: If synonyms is not a dict or None
        """
        self._validate_synonyms(synonyms)
        self.synonyms = synonyms or {}
        self.metrics = ReplacementMetrics()

    @staticmethod
    def _validate_synonyms(synonyms: Optional[Dict[str, str]]) -> None:
        """Validate synonyms dictionary format.
        
        Args:
            synonyms: Dictionary to validate
            
        Raises:
            TypeError: If synonyms is not a dict or None
            ValueError: If synonyms contains non-string keys or values
        """
        if synonyms is None:
            return
        
        if not isinstance(synonyms, dict):
            raise TypeError(f"Synonyms must be a dictionary, got {type(synonyms).__name__}")
        
        for key, value in synonyms.items():
            if not isinstance(key, str):
                raise ValueError(f"Synonym keys must be strings, got {type(key).__name__} for key: {key}")
            if not isinstance(value, str):
                raise ValueError(f"Synonym values must be strings, got {type(value).__name__} for value: {value}")

    def update_synonyms(self, synonyms: Dict[str, str]) -> None:
        """Update the synonyms dictionary at runtime (API-updatable).
        
        Args:
            synonyms: New synonyms dictionary
            
        Raises:
            TypeError: If synonyms is not a dict
            ValueError: If synonyms contains invalid keys or values
        """
        self._validate_synonyms(synonyms)
        self.synonyms = synonyms
        logger.info(f"Updated synonyms dictionary with {len(synonyms)} entries")

    def replace_synonyms(self, entities: Dict[str, str]) -> Dict[str, str]:
        """Replace extracted entity values with root words using synonyms dictionary.
        
        Args:
            entities: Dictionary of entity name to entity value mappings
            
        Returns:
            Dictionary with replaced entity values where applicable
            
        Raises:
            TypeError: If entities is not a dict
        """
        if not isinstance(entities, dict):
            raise TypeError(f"Entities must be a dictionary, got {type(entities).__name__}")
        
        self.metrics.total_replacements += len(entities)
        replaced_entities = entities.copy()
        
        for entity_key, entity_value in replaced_entities.items():
            entity_value_lower = str(entity_value).lower()
            if entity_value_lower in self.synonyms:
                replaced_entities[entity_key] = self.synonyms[entity_value_lower]
                self.metrics.replacement_hits += 1
                logger.debug(f"Replaced '{entity_value}' with '{self.synonyms[entity_value_lower]}'")
        
        return replaced_entities

    def get_metrics(self) -> Dict[str, Any]:
        """Get current replacement metrics.
        
        Returns:
            Dictionary containing replacement metrics
        """
        return self.metrics.to_dict()

    def reset_metrics(self) -> None:
        """Reset replacement metrics."""
        self.metrics = ReplacementMetrics()


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda handler for synonym replacement.
    
    Supports two operations:
    1. replace: Replace synonyms in entities
    2. update: Update the synonyms dictionary
    
    Args:
        event: Lambda event containing:
            - operation: 'replace' or 'update'
            - synonyms: (for update) new synonyms dict
            - entities: (for replace) entities to process
        context: Lambda context object
        
    Returns:
        Dictionary containing:
            - statusCode: HTTP status code
            - body: Response body with results or error
            - metrics: Replacement metrics (for replace operation)
    """
    try:
        operation = event.get("operation", "replace")
        
        # Initialize replacer with existing synonyms if provided
        initial_synonyms = event.get("synonyms", {})
        replacer = SynonymReplacer(synonyms=initial_synonyms)
        
        if operation == "replace":
            entities = event.get("entities", {})
            if not entities:
                return {
                    "statusCode": 400,
                    "body": {"error": "Missing 'entities' in event"},
                }
            
            replaced = replacer.replace_synonyms(entities)
            return {
                "statusCode": 200,
                "body": {
                    "entities": replaced,
                    "metrics": replacer.get_metrics(),
                },
            }
        
        elif operation == "update":
            new_synonyms = event.get("synonyms", {})
            if not new_synonyms:
                return {
                    "statusCode": 400,
                    "body": {"error": "Missing 'synonyms' in event for update operation"},
                }
            
            replacer.update_synonyms(new_synonyms)
            return {
                "statusCode": 200,
                "body": {
                    "message": f"Updated {len(new_synonyms)} synonym entries",
                    "count": len(new_synonyms),
                },
            }
        
        else:
            return {
                "statusCode": 400,
                "body": {"error": f"Unknown operation: {operation}"},
            }
    
    except (TypeError, ValueError) as e:
        logger.error(f"Validation error: {e}")
        return {
            "statusCode": 400,
            "body": {"error": str(e)},
        }
    except Exception as e:
        logger.error(f"Unexpected error in lambda_handler: {e}")
        return {
            "statusCode": 500,
            "body": {"error": "Internal server error"},
        }