"""
Entity schemas for CRUD APIs and NLU processing.

This module defines Pydantic models for entity data shapes used across
admin entity APIs, training tools, and dialogue manager integration.
Maintains separation from database-specific code except for ObjectId handling.
"""

from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from app.database import ObjectIdField


class EntityValue(BaseModel):
    """
    Schema for entity value with synonyms.
    
    Represents a single value within an entity type, including alternative
    names (synonyms) that should be recognized as equivalent.
    
    Attributes:
        value: The canonical value for this entity
        synonyms: List of alternative names for this value
    """

    value: str = Field(..., description="Canonical entity value")
    synonyms: List[str] = Field(
        default_factory=list,
        description="Alternative names for this entity value"
    )


class Entity(BaseModel):
    """
    Schema for entity with versioning support.
    
    Represents an entity type used for NLU and dialogue management.
    Includes metadata for tracking changes and migrations.
    
    Attributes:
        id: MongoDB ObjectId for the entity document
        name: Unique name of the entity type
        entity_values: List of values and synonyms for this entity
        version: Schema version for migration tracking
        created_at: Timestamp when entity was created
        updated_at: Timestamp of last modification
    """

    id: ObjectIdField = Field(
        default=None,
        validation_alias="_id",
        description="MongoDB ObjectId identifier"
    )
    name: str = Field(..., description="Unique entity type name")
    entity_values: List[EntityValue] = Field(
        default_factory=list,
        description="List of entity values and their synonyms"
    )
    version: int = Field(
        default=1,
        description="Schema version for migration tracking"
    )
    created_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when entity was created"
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of last modification"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)