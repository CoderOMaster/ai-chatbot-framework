from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List
from shared.database import ObjectIdField


class EntityValue(BaseModel):
    """Schema for entity value"""

    value: str
    synonyms: List[str] = []


class Entity(BaseModel):
    """Schema for entity"""

    id: ObjectIdField = Field(validation_alias="_id", default=None)
    name: str
    entity_values: List[EntityValue] = []

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("name")
    @classmethod
    def validate_entity_name_uniqueness(cls, v: str) -> str:
        """Validate entity name is not empty and provide uniqueness hint."""
        if not v or not v.strip():
            raise ValueError("Entity name cannot be empty")
        return v.strip()