from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional

from app.core.types import ObjectIdField


class EntityValue(BaseModel):
    """Schema for an entity value with optional synonyms.

    This model is DB-agnostic and safe to serialize across HTTP APIs and
    message queues (no database-only fields or internals).
    """

    value: str
    synonyms: List[str] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)


class Entity(BaseModel):
    """Schema for an entity.

    The primary identifier is optional to keep models decoupled from
    persistence details; storage backends should assign IDs on write.
    Lists use default_factory to avoid shared mutable defaults.
    """

    id: Optional[ObjectIdField] = Field(validation_alias="_id", default=None)
    name: str
    entity_values: List[EntityValue] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)