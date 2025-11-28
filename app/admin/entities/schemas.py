from typing import List

from core.types import ObjectIdField
from pydantic import BaseModel, ConfigDict, Field


class EntityValue(BaseModel):
    """Schema for entity value"""

    value: str
    synonyms: List[str] = Field(default_factory=list)


class Entity(BaseModel):
    """Schema for entity"""

    id: ObjectIdField = Field(validation_alias="_id", default=None)
    name: str
    entity_values: List[EntityValue] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)