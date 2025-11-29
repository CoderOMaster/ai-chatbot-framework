from typing import Any, List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class EntityValue(BaseModel):
    """Schema for entity value"""

    value: str
    synonyms: List[str] = Field(default_factory=list)


class Entity(BaseModel):
    """Schema for entity"""

    id: Optional[Any] = Field(validation_alias="_id", serialization_alias="_id", default=None)
    name: str
    entity_values: List[EntityValue] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    @field_validator("id", mode="before")
    @classmethod
    def validate_id(cls, value):
        """Validate and convert id to ObjectId if it's a string, otherwise pass through."""
        if isinstance(value, ObjectId):
            return value
        if value is None:
            return None
        # If it's not a string or bytes, it's likely an arbitrary type - pass it through
        if not isinstance(value, (str, bytes)):
            return value
        try:
            return ObjectId(value)
        except (InvalidId, TypeError) as e:
            raise ValueError(f"Invalid ObjectId: {str(e)}")

    @field_serializer("id")
    def serialize_id(self, value: Any) -> Any:
        """Serialize ObjectId to string, pass through other types."""
        if isinstance(value, ObjectId):
            return str(value)
        return value