from typing import List, Optional, Annotated, Dict

from pydantic import BaseModel, Field, ConfigDict

from app.database import ObjectIdField


def _to_camel(s: str) -> str:
    """Convert snake_case names to camelCase for consistent aliasing."""
    parts = s.split("_")
    if not parts:
        return s
    return parts[0] + "".join(p.title() for p in parts[1:])


# Constrained non-empty string type used across entity schemas
NonEmptyStr = Annotated[str, Field(min_length=1)]


class EntityValue(BaseModel):
    """Schema for a single entity value and its synonyms.

    Attributes:
        value: The canonical value for this entity entry (must be non-empty).
        synonyms: A list of alternative surface forms for the value.
    """

    value: NonEmptyStr
    synonyms: List[NonEmptyStr] = Field(default_factory=list)

    # Ensure consistent alias generation and allow any non-pydantic types if needed
    model_config = ConfigDict(arbitrary_types_allowed=True, alias_generator=_to_camel, populate_by_name=True)


class Entity(BaseModel):
    """Schema representing an entity used by admin APIs and training jobs.

    Provides helper methods to surface flattened synonym data for analytics.
    """

    id: Optional[ObjectIdField] = Field(default=None, validation_alias="_id")
    name: NonEmptyStr
    entity_values: List[EntityValue] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True, alias_generator=_to_camel, populate_by_name=True)

    def get_all_values(self) -> List[str]:
        """Return a list of all canonical values for this entity."""
        return [ev.value for ev in self.entity_values]

    def get_flat_synonyms(self) -> List[str]:
        """Return a deduplicated, flat list of all synonyms across entity values in insertion order."""
        seen = set()
        flattened: List[str] = []
        for ev in self.entity_values:
            for syn in ev.synonyms:
                if syn not in seen:
                    seen.add(syn)
                    flattened.append(syn)
        return flattened

    def get_value_synonym_map(self) -> Dict[str, List[str]]:
        """Return a mapping from each canonical value to its list of synonyms."""
        return {ev.value: list(ev.synonyms) for ev in self.entity_values}