from shared.database import ObjectIdField
from pydantic import BaseModel, Field, ConfigDict, HttpUrl, field_validator
from typing import List, Optional, Dict, Any
from bson import ObjectId


def generate_object_id() -> str:
    """Generate a new MongoDB ObjectId as a string."""
    return str(ObjectId())


class LabeledSentences(BaseModel):
    """Schema for labeled sentences used in intent training data."""

    id: ObjectIdField = Field(default_factory=generate_object_id)
    data: List[str] = []

    model_config = ConfigDict(arbitrary_types_allowed=True)


class Parameter(BaseModel):
    """Parameter schema for intent parameters.
    
    Attributes:
        id: Unique identifier for the parameter
        name: Parameter name
        required: Whether the parameter is required
        type: Parameter data type
        prompt: Prompt text to request the parameter from user
    """

    id: ObjectIdField = Field(default_factory=generate_object_id)
    name: str
    required: bool = False
    type: Optional[str] = None
    prompt: Optional[str] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ApiDetails(BaseModel):
    """API details schema for intent API triggers.
    
    Attributes:
        url: API endpoint URL (must be valid HTTP/HTTPS URL)
        requestType: HTTP method (GET, POST, PUT, DELETE, etc.)
        headers: List of header dictionaries with headerKey and headerValue
        isJson: Whether request body is JSON
        jsonData: JSON request body as string
    """

    url: str
    requestType: str
    headers: List[Dict[str, str]] = []
    isJson: bool = False
    jsonData: str = "{}"

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate that URL is a valid HTTP/HTTPS URL."""
        if not v:
            raise ValueError('URL cannot be empty')
        if not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError('URL must start with http:// or https://')
        return v

    def get_headers(self) -> Dict[str, str]:
        """Convert headers list to dictionary format.
        
        Returns:
            Dictionary mapping header keys to values
        """
        headers = {}
        for header in self.headers:
            headers[header["headerKey"]] = header["headerValue"]
        return headers


class Intent(BaseModel):
    """Base schema for intent.
    
    Represents a conversational intent with training data, parameters, and optional API triggers.
    
    Attributes:
        id: Unique MongoDB ObjectId for the intent
        name: Human-readable intent name
        userDefined: Whether intent was created by user (vs. system-defined)
        intentId: Unique string identifier for the intent
        apiTrigger: Whether this intent triggers an API call
        apiDetails: API configuration if apiTrigger is True
        speechResponse: Response text to return to user
        parameters: List of parameters the intent can extract
        labeledSentences: Training sentences labeled with this intent
        trainingData: Structured training data for NLU model. Each item should contain:
            - 'text': User utterance
            - 'intent': Intent name
            - 'entities': List of extracted entities with 'entity', 'value', 'start', 'end'
    """

    id: ObjectIdField = Field(validation_alias="_id", default=None)
    name: str
    userDefined: bool = True
    intentId: str
    apiTrigger: bool = False
    apiDetails: Optional[ApiDetails] = None
    speechResponse: str
    parameters: List[Parameter] = []
    labeledSentences: List[LabeledSentences] = []
    trainingData: List[Dict[str, Any]] = []

    model_config = ConfigDict(arbitrary_types_allowed=True)