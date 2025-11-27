from typing import Any, Annotated, Dict, List, Optional, Tuple, Union
import json

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field


# Centralized ObjectId handling utilities
ObjectIdField = Annotated[ObjectId, Field()]


def generate_object_id() -> ObjectId:
    """Generate a new BSON ObjectId.

    Returns:
        ObjectId: a new ObjectId instance.
    """
    return ObjectId()


def to_object_id(value: Union[str, ObjectId]) -> ObjectId:
    """Convert a string or ObjectId to an ObjectId instance.

    Args:
        value: a hex string or ObjectId

    Returns:
        ObjectId: the corresponding ObjectId instance
    """
    if isinstance(value, ObjectId):
        return value
    return ObjectId(str(value))


def to_str_id(value: Union[str, ObjectId]) -> str:
    """Return the hex string representation of an ObjectId or string input."""
    if isinstance(value, ObjectId):
        return str(value)
    return str(value)


class LabeledSentences(BaseModel):
    """Schema for labeled sentences attached to an intent."""

    id: ObjectIdField = Field(default_factory=generate_object_id)
    data: List[str] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)


class Parameter(BaseModel):
    """Parameter schema for intent parameters."""

    id: ObjectIdField = Field(default_factory=generate_object_id)
    name: str
    required: bool = False
    type: Optional[str] = None
    prompt: Optional[str] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ApiDetails(BaseModel):
    """API details schema for intent API triggers.

    Provides helpers to convert header lists to dicts and validate trigger payloads
    received from external callers (e.g. the admin API).
    """

    url: str
    requestType: str
    headers: List[Dict[str, str]] = Field(default_factory=list)
    isJson: bool = False
    jsonData: str = "{}"

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def get_headers(self) -> Dict[str, str]:
        """Return headers as a simple key->value dict.

        When duplicate header keys are present the last occurrence wins.
        """
        headers: Dict[str, str] = {}
        for header in self.headers:
            # Expected shape: {"headerKey": "...", "headerValue": "..."}
            key = header.get("headerKey") or header.get("key")
            value = header.get("headerValue") or header.get("value")
            if key is not None and value is not None:
                headers[key] = value
        return headers

    def validate_payload(self) -> Tuple[bool, List[str]]:
        """Validate the API trigger payload structure.

        Checks performed:
        - url is non-empty
        - requestType is a recognised HTTP method
        - headers are a list of dicts containing headerKey/headerValue or key/value
        - if isJson is True, jsonData must be valid JSON

        Returns:
            (bool, List[str]): (is_valid, list_of_error_messages)
        """
        errors: List[str] = []
        if not self.url or not isinstance(self.url, str):
            errors.append("url must be a non-empty string")

        valid_methods = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
        if not isinstance(self.requestType, str) or self.requestType.upper() not in valid_methods:
            errors.append(f"requestType must be one of: {', '.join(sorted(valid_methods))}")

        if not isinstance(self.headers, list):
            errors.append("headers must be a list of header objects")
        else:
            for i, h in enumerate(self.headers):
                if not isinstance(h, dict):
                    errors.append(f"headers[{i}] must be a dict")
                    continue
                if not (h.get("headerKey") or h.get("key")):
                    errors.append(f"headers[{i}] missing headerKey/key")
                if not (h.get("headerValue") or h.get("value")):
                    errors.append(f"headers[{i}] missing headerValue/value")

        if self.isJson:
            try:
                json.loads(self.jsonData or "{}")
            except Exception:
                errors.append("jsonData is not valid JSON")

        return (len(errors) == 0, errors)


class Intent(BaseModel):
    """Base schema for an intent used across admin API and storage.

    Uses centralized ObjectIdField and default factories for mutable fields to
    avoid shared mutable defaults.
    """

    id: Optional[ObjectIdField] = Field(default=None, alias="_id")
    name: str
    userDefined: bool = True
    intentId: str
    apiTrigger: bool = False
    apiDetails: Optional[ApiDetails] = None
    speechResponse: str
    parameters: List[Parameter] = Field(default_factory=list)
    labeledSentences: List[LabeledSentences] = Field(default_factory=list)
    trainingData: List[Dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)