from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, ConfigDict

from app.core.types import ObjectIdField


class LabeledSentences(BaseModel):
    """Schema for labeled sentences.

    IDs are optional here; ID generation should be performed by the
    persistence layer or an ID service during write operations rather than
    at model construction time.
    """

    id: Optional[ObjectIdField] = Field(default=None)
    data: List[str] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)


class Parameter(BaseModel):
    """Parameter schema for intent parameters.

    Keep IDs optional so storage backends may assign them.
    """

    id: Optional[ObjectIdField] = Field(default=None)
    name: str
    required: bool = False
    type: Optional[str] = None
    prompt: Optional[str] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ApiDetails(BaseModel):
    """API details schema for intent API triggers."""

    url: str
    requestType: str
    headers: List[Dict[str, str]] = Field(default_factory=list)
    isJson: bool = False
    jsonData: str = "{}"

    def get_headers(self) -> Dict[str, str]:
        """Return headers as a simple dict keyed by headerKey.

        The internal representation is a list of dicts with headerKey/headerValue
        to match existing API shapes; this helper normalizes them for requests.
        """
        headers: Dict[str, str] = {}
        for header in self.headers:
            headers[header["headerKey"]] = header["headerValue"]
        return headers


class Intent(BaseModel):
    """Base schema for intent.

    The primary identifier is optional; databases or ID services should
    populate it on writes. Lists use default_factory to avoid shared
    mutable defaults between instances.
    """

    id: Optional[ObjectIdField] = Field(validation_alias="_id", default=None)
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