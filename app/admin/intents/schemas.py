"""
Intent schema definitions for admin CRUD, training pipeline, and dialogue manager.

This module defines the canonical Intent schema contract shared across:
- Admin UI (CRUD operations)
- Training pipeline (model training and evaluation)
- Dialogue manager (runtime intent resolution)

Field categorization:
- Core fields: Required for all operations (name, intentId, speechResponse)
- Runtime fields: Used by dialogue manager (apiTrigger, apiDetails, parameters)
- Training fields: Used by training pipeline (labeledSentences, trainingData)
- Metadata fields: System-managed (id, userDefined)
"""

from app.database import ObjectIdField
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
from bson import ObjectId


def generate_object_id() -> str:
    """Generate a new MongoDB ObjectId as string."""
    return str(ObjectId())


class LabeledSentences(BaseModel):
    """
    Schema for labeled training sentences.
    
    Used by the training pipeline to store example utterances for intent classification.
    Each labeled sentence is associated with a specific intent for supervised learning.
    
    Attributes:
        id: Unique identifier for this labeled sentence batch
        data: List of example utterances/sentences for training
    """

    id: ObjectIdField = Field(default_factory=generate_object_id)
    data: List[str] = Field(default_factory=list, description="List of training sentences")

    model_config = ConfigDict(arbitrary_types_allowed=True)


class Parameter(BaseModel):
    """
    Schema for intent parameters extracted from user utterances.
    
    Parameters represent slots or entities that the intent can extract from
    user input. Used by both training (to label parameters in sentences) and
    runtime (to extract and validate parameters from dialogue).
    
    Attributes:
        id: Unique identifier for this parameter
        name: Parameter name (e.g., "location", "date", "amount")
        required: Whether this parameter must be present for intent execution
        type: Optional type hint for parameter validation (e.g., "string", "number", "date")
        prompt: Optional prompt to ask user if parameter is missing
    """

    id: ObjectIdField = Field(default_factory=generate_object_id)
    name: str = Field(description="Parameter name/slot identifier")
    required: bool = Field(default=False, description="Whether parameter is required")
    type: Optional[str] = Field(default=None, description="Parameter type hint")
    prompt: Optional[str] = Field(default=None, description="Prompt if parameter is missing")

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ApiDetails(BaseModel):
    """
    Schema for API trigger configuration.
    
    Defines how the dialogue manager should invoke external APIs when this intent
    is triggered. Used at runtime to execute side effects (e.g., booking, payment).
    
    Attributes:
        url: API endpoint URL
        requestType: HTTP method (GET, POST, PUT, DELETE, etc.)
        headers: List of header key-value pairs
        isJson: Whether request body should be JSON-encoded
        jsonData: JSON payload template as string
    """

    url: str = Field(description="API endpoint URL")
    requestType: str = Field(description="HTTP method (GET, POST, etc.)")
    headers: List[Dict[str, str]] = Field(
        default_factory=list,
        description="List of header dictionaries with 'headerKey' and 'headerValue'"
    )
    isJson: bool = Field(default=False, description="Whether to send JSON payload")
    jsonData: str = Field(default="{}", description="JSON payload template")

    def get_headers(self) -> Dict[str, str]:
        """
        Convert header list to dictionary format.
        
        Returns:
            Dictionary mapping header keys to values
        """
        headers = {}
        for header in self.headers:
            headers[header["headerKey"]] = header["headerValue"]
        return headers


class Intent(BaseModel):
    """
    Canonical Intent schema for admin, training, and runtime services.
    
    This schema represents the complete intent definition used across the system:
    
    Core fields (required for all operations):
    - id, name, intentId, speechResponse
    
    Runtime fields (used by dialogue manager):
    - apiTrigger, apiDetails, parameters
    
    Training fields (used by training pipeline):
    - labeledSentences, trainingData
    
    Metadata fields (system-managed):
    - userDefined
    
    Attributes:
        id: MongoDB ObjectId, used as primary key in database
        name: Human-readable intent name (e.g., "book_flight")
        userDefined: Whether this is a custom user-defined intent (vs system intent)
        intentId: Unique identifier for intent (used in dialogue state)
        apiTrigger: Whether this intent triggers an external API call
        apiDetails: API configuration if apiTrigger is True
        speechResponse: Default response template to user (may include parameter placeholders)
        parameters: List of parameters/slots this intent can extract
        labeledSentences: Training examples for intent classification
        trainingData: Additional training metadata (e.g., confidence scores, evaluation metrics)
    """

    id: ObjectIdField = Field(
        validation_alias="_id",
        default=None,
        description="MongoDB ObjectId primary key"
    )
    name: str = Field(description="Human-readable intent name")
    userDefined: bool = Field(
        default=True,
        description="Whether this is a user-defined intent"
    )
    intentId: str = Field(description="Unique intent identifier for dialogue state")
    apiTrigger: bool = Field(
        default=False,
        description="Whether this intent triggers an external API"
    )
    apiDetails: Optional[ApiDetails] = Field(
        default=None,
        description="API configuration (required if apiTrigger is True)"
    )
    speechResponse: str = Field(description="Response template for user")
    parameters: List[Parameter] = Field(
        default_factory=list,
        description="Parameters/slots this intent can extract"
    )
    labeledSentences: List[LabeledSentences] = Field(
        default_factory=list,
        description="Training examples for intent classification"
    )
    trainingData: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Training metadata (confidence scores, evaluation metrics, etc.)"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)