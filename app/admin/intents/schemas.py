"""Intent schemas for chatbot functionality with validation."""
from app.database import ObjectIdField
from app.admin.intents.api_details import ApiDetails
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from bson import ObjectId


def generate_object_id() -> str:
    """Generate a new ObjectId as string.

    Returns:
        String representation of a new ObjectId
    """
    return str(ObjectId())


class LabeledSentences(BaseModel):
    """Schema for labeled sentences used in intent training."""

    id: ObjectIdField = Field(default_factory=generate_object_id)
    data: List[str] = Field(default_factory=list, description="List of labeled sentences")

    class Config:
        arbitrary_types_allowed = True


class Parameter(BaseModel):
    """Parameter schema for intent parameters with type constraints."""

    id: ObjectIdField = Field(default_factory=generate_object_id)
    name: str = Field(..., min_length=1, description="Parameter name")
    required: bool = Field(default=False, description="Whether parameter is required")
    type: Optional[str] = Field(
        default=None,
        description="Parameter type (e.g., 'string', 'number', 'boolean', 'date')"
    )
    prompt: Optional[str] = Field(default=None, description="Prompt text for parameter collection")

    class Config:
        arbitrary_types_allowed = True

    @field_validator("type")
    @classmethod
    def validate_parameter_type(cls, v: Optional[str]) -> Optional[str]:
        """Validate that parameter type is one of allowed types.

        Args:
            v: Parameter type string to validate

        Returns:
            Validated parameter type or None

        Raises:
            ValueError: If parameter type is not in allowed types
        """
        if v is None:
            return v
        allowed_types = {"string", "number", "boolean", "date", "email", "url", "phone"}
        if v.lower() not in allowed_types:
            raise ValueError(f"Parameter type must be one of {allowed_types}, got '{v}'")
        return v.lower()

    @field_validator("name")
    @classmethod
    def validate_parameter_name(cls, v: str) -> str:
        """Validate that parameter name is valid identifier.

        Args:
            v: Parameter name to validate

        Returns:
            Validated parameter name

        Raises:
            ValueError: If parameter name is not a valid identifier
        """
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Parameter name must contain only alphanumeric characters, hyphens, and underscores")
        return v


class Intent(BaseModel):
    """Base schema for intent with comprehensive validation."""

    id: ObjectIdField = Field(validation_alias="_id", default=None)
    name: str = Field(..., min_length=1, description="Intent name (must be unique)")
    userDefined: bool = Field(default=True, description="Whether intent is user-defined")
    intentId: str = Field(..., min_length=1, description="Unique intent identifier")
    apiTrigger: bool = Field(default=False, description="Whether intent is triggered by API")
    apiDetails: Optional[ApiDetails] = Field(default=None, description="API trigger details")
    speechResponse: str = Field(..., min_length=1, description="Speech response text")
    parameters: List[Parameter] = Field(default_factory=list, description="Intent parameters")
    labeledSentences: List[LabeledSentences] = Field(default_factory=list, description="Labeled training sentences")
    trainingData: List[Dict[str, Any]] = Field(default_factory=list, description="Additional training data")

    class Config:
        arbitrary_types_allowed = True

    @field_validator("name")
    @classmethod
    def validate_intent_name(cls, v: str) -> str:
        """Validate intent name format.

        Args:
            v: Intent name to validate

        Returns:
            Validated intent name

        Raises:
            ValueError: If intent name is invalid
        """
        if not v or not v.strip():
            raise ValueError("Intent name cannot be empty")
        if len(v) > 255:
            raise ValueError("Intent name must not exceed 255 characters")
        return v.strip()

    @field_validator("intentId")
    @classmethod
    def validate_intent_id(cls, v: str) -> str:
        """Validate intent ID format.

        Args:
            v: Intent ID to validate

        Returns:
            Validated intent ID

        Raises:
            ValueError: If intent ID is invalid
        """
        if not v or not v.strip():
            raise ValueError("Intent ID cannot be empty")
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Intent ID must contain only alphanumeric characters, hyphens, and underscores")
        return v.strip()

    @field_validator("apiDetails")
    @classmethod
    def validate_api_trigger_consistency(cls, v: Optional[ApiDetails], info) -> Optional[ApiDetails]:
        """Validate that apiDetails is provided when apiTrigger is True.

        Args:
            v: API details to validate
            info: Validation context with other field values

        Returns:
            Validated API details

        Raises:
            ValueError: If apiTrigger is True but apiDetails is missing
        """
        if info.data.get("apiTrigger") and not v:
            raise ValueError("apiDetails must be provided when apiTrigger is True")
        if not info.data.get("apiTrigger") and v:
            raise ValueError("apiDetails should not be provided when apiTrigger is False")
        return v