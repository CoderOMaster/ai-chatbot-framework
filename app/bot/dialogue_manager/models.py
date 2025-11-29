from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional, Text

from app.admin.intents.schemas import Intent


@dataclass
class ApiDetailsModel:
    """Represents the configuration needed to invoke an external API during intent handling."""

    url: str
    request_type: str
    headers: List[Dict[str, str]]
    is_json: bool = False
    json_data: str = "{}"

    def get_headers(self) -> Dict[str, str]:
        """Return the headers as a simple key/value mapping."""

        headers: Dict[str, str] = {}
        for header in self.headers:
            headers[header["headerKey"]] = header["headerValue"]
        return headers


@dataclass
class ParameterModel:
    """Describes a single parameter that can be extracted from user input."""

    name: str
    required: bool = False
    type: Optional[str] = None
    prompt: Optional[str] = None


@dataclass
class IntentModel:
    """Domain representation of an intent processed by the dialogue manager."""

    name: str
    intent_id: str
    speech_response: str
    user_defined: bool = True
    api_trigger: bool = False
    api_details: Optional[ApiDetailsModel] = None
    parameters: List[ParameterModel] = None

    def __post_init__(self) -> None:
        if self.parameters is None:
            self.parameters = []

    @classmethod
    def from_db(cls, db_intent: Intent) -> "IntentModel":
        """Map the admin intent schema into the dialogue manager domain intent."""

        api_details: Optional[ApiDetailsModel] = None
        if db_intent.apiDetails:
            api_details = ApiDetailsModel(
                url=db_intent.apiDetails.url,
                request_type=db_intent.apiDetails.requestType,
                headers=db_intent.apiDetails.headers,
                is_json=db_intent.apiDetails.isJson,
                json_data=db_intent.apiDetails.jsonData,
            )

        parameters: List[ParameterModel] = []
        if db_intent.parameters:
            parameters = [
                ParameterModel(
                    name=p.name,
                    required=p.required,
                    type=p.type,
                    prompt=p.prompt,
                )
                for p in db_intent.parameters
            ]

        return cls(
            name=db_intent.name,
            intent_id=db_intent.intentId,
            speech_response=db_intent.speechResponse,
            user_defined=db_intent.userDefined,
            api_trigger=db_intent.apiTrigger,
            api_details=api_details,
            parameters=parameters,
        )


class ChatModel:
    """In-memory representation of a chat session for scoring dialogue flows and state."""

    def __init__(
        self,
        input_text: str,
        context: Optional[Dict[str, Any]] = None,
        intent: Optional[Dict[str, Any]] = None,
        extracted_parameters: Optional[Dict[str, Any]] = None,
        missing_parameters: Optional[List[str]] = None,
        complete: bool = False,
        speech_response: Optional[List[str]] = None,
        current_node: str = "",
        parameters: Optional[List[Dict[str, Any]]] = None,
        owner: str = "",
        date: Optional[str] = None,
    ) -> None:
        self.input_text = input_text
        self.context = context or {}
        self.intent = intent or {}
        self.nlu: Dict[str, Any] = {}
        self.extracted_parameters = extracted_parameters or {}
        self.missing_parameters = missing_parameters or []
        self.complete = complete
        self.speech_response = speech_response or []
        self.current_node = current_node
        self.parameters = parameters or []
        self.owner = owner
        self.date = date or datetime.now(UTC).isoformat()

    @classmethod
    def from_json(cls, request_json: Dict[str, Any]) -> "ChatModel":
        """Create a ChatModel instance from a serialized payload."""

        return cls(
            input_text=request_json.get("input", ""),
            context=request_json.get("context", {}),
            intent=request_json.get("intent", {}),
            extracted_parameters=request_json.get("extractedParameters", {}),
            missing_parameters=request_json.get("missingParameters", []),
            complete=request_json.get("complete", False),
            speech_response=request_json.get("speechResponse", []),
            current_node=request_json.get("currentNode", ""),
            parameters=request_json.get("parameters", []),
            owner=request_json.get("owner", ""),
            date=request_json.get("date"),
        )

    def to_json(self) -> Dict[str, Any]:
        """Serialize the chat state into JSON-compatible primitives."""

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
        """Create a deep copy of this chat state for isolated processing."""

        return deepcopy(self)

    def reset(self) -> None:
        """Clear the intent tracking state while preserving chat metadata."""

        self.complete = False
        self.intent = {}
        self.missing_parameters = []
        self.extracted_parameters = {}
        self.parameters = []
        self.current_node = ""
        self.speech_response = []


class UserMessage:
    """Neutral carrier for a user message passing between memory and channel layers."""

    def __init__(
        self,
        thread_id: str,
        text: Text,
        context: Dict[str, Any],
        channel: Text = "rest",
    ) -> None:
        self.thread_id = thread_id
        self.text = text
        self.channel = channel
        self.context = context

    def to_dict(self) -> Dict[str, Any]:
        """Convert the message into a dictionary for serialization or transport."""

        return {
            "thread_id": self.thread_id,
            "text": self.text,
            "channel": self.channel,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserMessage":
        """Rehydrate a UserMessage from a simple dictionary payload."""

        return cls(
            thread_id=data["thread_id"],
            text=data["text"],
            context=data["context"],
            channel=data.get("channel", "rest"),
        )