from typing import Optional, Dict, List, Any, Text, TYPE_CHECKING
from datetime import datetime, timezone
from copy import deepcopy
from dataclasses import dataclass, field

if TYPE_CHECKING:
    # Keep a typing-only dependency on the admin Intent schema for the mapping concern
    from app.admin.intents.schemas import Intent


@dataclass
class ApiDetailsModel:
    """Domain model for external API invocation details.

    Attributes:
        url: The endpoint URL.
        request_type: HTTP method (e.g. 'GET', 'POST').
        headers: List of header mappings as stored in admin schema.
        is_json: Whether the payload is JSON.
        json_data: Default JSON payload as string.
    """

    url: str
    request_type: str
    headers: List[Dict[str, str]] = field(default_factory=list)
    is_json: bool = False
    json_data: str = "{}"

    def get_headers(self) -> Dict[str, str]:
        """Normalize header representations to a simple dict.

        Expected header entries to contain keys 'headerKey' and 'headerValue'
        as produced by the admin intent schema. Missing or unexpected
        structures are ignored.
        """
        headers: Dict[str, str] = {}
        for header in self.headers:
            # guard against unexpected shapes
            key = header.get("headerKey") or header.get("key")
            value = header.get("headerValue") or header.get("value")
            if key and value:
                headers[str(key)] = str(value)
        return headers


@dataclass
class ParameterModel:
    """Domain representation of an intent parameter."""

    name: str
    required: bool = False
    type: Optional[str] = None
    prompt: Optional[str] = None


@dataclass
class IntentModel:
    """Pure domain model for an intent used by the dialogue manager.

    The from_db classmethod maps from the admin Intent schema into this
    neutral representation. This module deliberately avoids importing any
    database or HTTP framework code at runtime; the dependency on the admin
    schema is type-only for mapping purposes.
    """

    name: str
    intent_id: str
    speech_response: str
    user_defined: bool = True
    api_trigger: bool = False
    api_details: Optional[ApiDetailsModel] = None
    parameters: List[ParameterModel] = field(default_factory=list)

    @classmethod
    def from_db(cls, db_intent: "Intent") -> "IntentModel":
        """Map an admin.intent.schema.Intent instance to IntentModel.

        This method performs a best-effort mapping of commonly-used fields
        and tolerates missing attributes to avoid leaking admin framework
        errors into the dialogue-manager domain.
        """
        api_details = None
        if getattr(db_intent, "apiDetails", None):
            api = db_intent.apiDetails
            api_details = ApiDetailsModel(
                url=getattr(api, "url", ""),
                request_type=getattr(api, "requestType", "GET"),
                headers=getattr(api, "headers", []) or [],
                is_json=getattr(api, "isJson", False),
                json_data=getattr(api, "jsonData", "{}"),
            )

        parameters: List[ParameterModel] = []
        for p in getattr(db_intent, "parameters", []) or []:
            parameters.append(
                ParameterModel(
                    name=getattr(p, "name", ""),
                    required=getattr(p, "required", False),
                    type=getattr(p, "type", None),
                    prompt=getattr(p, "prompt", None),
                )
            )

        return cls(
            name=getattr(db_intent, "name", ""),
            intent_id=getattr(db_intent, "intentId", ""),
            speech_response=getattr(db_intent, "speechResponse", ""),
            user_defined=getattr(db_intent, "userDefined", True),
            api_trigger=getattr(db_intent, "apiTrigger", False),
            api_details=api_details,
            parameters=parameters,
        )


@dataclass
class ChatModel:
    """In-memory representation of a chat/session used by dialogue flow logic."""

    input_text: str
    context: Dict[str, Any] = field(default_factory=dict)
    intent: Dict[str, Any] = field(default_factory=dict)
    extracted_parameters: Dict[str, Any] = field(default_factory=dict)
    missing_parameters: List[str] = field(default_factory=list)
    complete: bool = False
    speech_response: List[str] = field(default_factory=list)
    current_node: str = ""
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    owner: str = ""
    date: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    nlu: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, request_json: Dict[str, Any]) -> "ChatModel":
        return cls(
            input_text=request_json.get("input", ""),
            context=request_json.get("context", {}) or {},
            intent=request_json.get("intent", {}) or {},
            extracted_parameters=request_json.get("extractedParameters", {}) or {},
            missing_parameters=request_json.get("missingParameters", []) or [],
            complete=request_json.get("complete", False),
            speech_response=request_json.get("speechResponse", []) or [],
            current_node=request_json.get("currentNode", "") or "",
            parameters=request_json.get("parameters", []) or [],
            owner=request_json.get("owner", "") or "",
            date=request_json.get("date", None),
        )

    def to_json(self) -> Dict[str, Any]:
        return {
            "input": self.input_text,
            "context": self.context,
            "intent": self.intent,
            "nlu": self.nlu,
            "extractedParameters": self.extracted_parameters,
            "missingParameters": self.missing_parameters,
            "complete": self.complete,
            "speechResponse": self.speech_response,
            "currentNode": self.current_node,
            "parameters": self.parameters,
            "owner": self.owner,
            "date": self.date,
        }

    def clone(self) -> "ChatModel":
        return deepcopy(self)

    def reset(self) -> None:
        """Reset the chat state while keeping structural defaults intact."""
        self.complete = False
        self.intent = {}
        self.missing_parameters = []
        self.extracted_parameters = {}
        self.parameters = []
        self.current_node = ""
        self.speech_response = []
        self.nlu = {}


@dataclass
class UserMessage:
    """Neutral representation of an incoming user message across channels.

    Kept in the dialogue-manager package so memory and channel adapters can
    share a simple, serializable structure.
    """

    thread_id: str
    text: Text
    context: Dict[str, Any] = field(default_factory=dict)
    channel: Text = "rest"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "text": self.text,
            "channel": self.channel,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserMessage":
        return cls(
            thread_id=data["thread_id"],
            text=data["text"],
            context=data.get("context", {}) or {},
            channel=data.get("channel", "rest"),
        )