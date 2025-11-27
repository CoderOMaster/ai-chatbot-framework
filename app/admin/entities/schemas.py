from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional
from app.database import ObjectIdField


class EntityValue(BaseModel):
    """Schema for entity value with validation constraints."""

    value: str = Field(min_length=1, max_length=500)
    synonyms: List[str] = Field(default=[], max_length=50)

    @field_validator("value")
    @classmethod
    def validate_value_length(cls, v: str) -> str:
        """Ensure value is not empty after stripping whitespace."""
        if not v.strip():
            raise ValueError("Value cannot be empty or whitespace only")
        return v.strip()

    @field_validator("synonyms")
    @classmethod
    def validate_synonyms(cls, v: List[str]) -> List[str]:
        """Ensure each synonym is valid and within length constraints."""
        for synonym in v:
            if not synonym.strip():
                raise ValueError("Synonyms cannot be empty or whitespace only")
            if len(synonym) > 500:
                raise ValueError("Each synonym must not exceed 500 characters")
        return [s.strip() for s in v]


class Entity(BaseModel):
    """Schema for entity with full details including ID."""

    id: ObjectIdField = Field(validation_alias="_id", default=None)
    name: str = Field(min_length=1, max_length=255)
    entity_values: List[EntityValue] = Field(default=[])

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate entity name: alphanumeric, underscores, hyphens, and spaces only."""
        if not v.strip():
            raise ValueError("Name cannot be empty or whitespace only")
        
        # Allow alphanumeric, underscores, hyphens, and spaces
        import re
        if not re.match(r"^[a-zA-Z0-9\s_-]+$", v):
            raise ValueError(
                "Name can only contain alphanumeric characters, spaces, underscores, and hyphens"
            )
        return v.strip()


class EntityCreate(BaseModel):
    """Schema for creating a new entity."""

    name: str = Field(min_length=1, max_length=255)
    entity_values: List[EntityValue] = Field(default=[])

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate entity name: alphanumeric, underscores, hyphens, and spaces only."""
        if not v.strip():
            raise ValueError("Name cannot be empty or whitespace only")
        
        import re
        if not re.match(r"^[a-zA-Z0-9\s_-]+$", v):
            raise ValueError(
                "Name can only contain alphanumeric characters, spaces, underscores, and hyphens"
            )
        return v.strip()


class EntityUpdate(BaseModel):
    """Schema for updating an existing entity."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    entity_values: Optional[List[EntityValue]] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        """Validate entity name: alphanumeric, underscores, hyphens, and spaces only."""
        if v is None:
            return v
        
        if not v.strip():
            raise ValueError("Name cannot be empty or whitespace only")
        
        import re
        if not re.match(r"^[a-zA-Z0-9\s_-]+$", v):
            raise ValueError(
                "Name can only contain alphanumeric characters, spaces, underscores, and hyphens"
            )
        return v.strip()