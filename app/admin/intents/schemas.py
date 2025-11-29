"""Intent-related schema definitions shared between admin APIs and dialogue manager."""
from typing import Any, Dict, List, Optional

from core.types import ObjectIdField
from pydantic import BaseModel, ConfigDict, Field


class LabeledSentences(BaseModel):
    """Schema for labeled sentences"""

    id: Optional[ObjectIdField] = None
    data: List[str] = []

    model_config = ConfigDict(arbitrary_types_allowed=True)


class Parameter(BaseModel):
    """Parameter schema for intent parameters"""

    id: Optional[ObjectIdField] = None
    name: str
    required: bool = False
    type: Optional[str] = None
    prompt: Optional[str] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ApiDetails(BaseModel):
    """API details schema for intent API triggers"""

    url: str
    requestType: str
    headers: List[Dict[str, str]] = []
    isJson: bool = False
    jsonData: str = "{}"

    def get_headers(self) -> Dict[str, str]:
        """Return headers keyed by header key name."""

        headers = {}
        for header in self.headers:
            headers[header["headerKey"]] = header["headerValue"]
        return headers


class Intent(BaseModel):
    """Base schema for intent"""

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