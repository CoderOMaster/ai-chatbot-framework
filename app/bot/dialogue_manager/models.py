from typing import Optional, Dict, List, Any, Mapping, Union
from datetime import datetime, timezone
from copy import deepcopy
from dataclasses import dataclass, field


def _get(data: Any, *names: str, default: Any = None) -> Any:
    """Helper to retrieve a value from either a mapping or an object's attribute.

    Tries each name in order and returns the first non-None value found.
    """
    for name in names:
        if isinstance(data, Mapping):
            if name in data and data[name] is not None:
                return data[name]
        else:
            val = getattr(data, name, None)
            if val is not None:
                return val
    return default


@dataclass(frozen=True)
class ApiDetailsModel:
    """Immutable model representing API trigger details.

    Factory methods accept either a mapping (dict) or an object with attributes
    (e.g. a Pydantic model) to avoid a hard dependency on the admin Intent class.
    """

    url: str
    request_type: str
    headers: List[Dict[str, str]] = field(default_factory=list)
    is_json: bool = False
    json_data: str = "{}"

    def get_headers(self) -> Dict[str, str]:
        """Return headers as a key->value dict.

        Accepts header entries with keys like 'headerKey'/'headerValue' or
        'key'/'value'. When duplicates exist, the last occurrence wins.
        """
        result: Dict[str, str] = {}
        for header in self.headers:
            key = header.get("headerKey") or header.get("key")
            value = header.get("headerValue") or header.get("value")
            if key is not None and value is not None:
                result[key] = value
        return result

    @classmethod
    def from_mapping(cls, data: Any) -> "ApiDetailsModel":
        """Create an ApiDetailsModel from a mapping or object-like schema.

        This method intentionally tolerates multiple naming conventions used by
        different layers (e.g. 'requestType' vs 'request_type').
        """
        url = _get(data, "url") or ""
        request_type = _get(data, "requestType", "request_type") or ""
        headers = _get(data, "headers", default=[]) or []
        is_json = _get(data, "isJson", "is_json", default=False) or False
        json_data = _get(data, "jsonData", "json_data", default="{}") or "{}"
        return cls(
            url=url,
            request_type=request_type,
            headers=list(headers),
            is_json=bool(is_json),
            json_data=str(json_data),
        )


@dataclass(frozen=True)
class ParameterModel:
    """Immutable model for intent parameters."""

    name: str
    required: bool = False
    type: Optional[str] = None
    prompt: Optional[str] = None

    @classmethod
    def from_mapping(cls, data: Any) -> "ParameterModel":
        name = _get(data, "name") or ""
        required = bool(_get(data, "required", default=False))
        p_type = _get(data, "type")
        prompt = _get(data, "prompt")
        return cls(name=name, required=required, type=p_type, prompt=prompt)


@dataclass(frozen=True)
class IntentModel:
    """Immutable domain intent model used by the dialogue manager.

    Provides factory methods that accept lightweight mappings/objects to avoid
    importing the admin Intent schema directly and reduce coupling.
    """

    name: str
    intent_id: str
    speech_response: str
    user_defined: bool = True
    api_trigger: bool = False
    api_details: Optional[ApiDetailsModel] = None
    parameters: List[ParameterModel] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Any) -> "IntentModel":
        """Create an IntentModel from a mapping or object-like schema.

        Expected fields (tolerant): name, intentId/intent_id, speechResponse/speech_response,
        userDefined/user_defined, apiTrigger/api_trigger, apiDetails, parameters.
        """
        name = _get(data, "name") or ""
        intent_id = _get(data, "intentId", "intent_id") or ""
        speech_response = _get(data, "speechResponse", "speech_response") or ""
        user_defined = bool(_get(data, "userDefined", "user_defined", default=True))
        api_trigger = bool(_get(data, "apiTrigger", "api_trigger", default=False))

        raw_api = _get(data, "apiDetails", default=None)
        api_details = ApiDetailsModel.from_mapping(raw_api) if raw_api is not None else None

        raw_params = _get(data, "parameters", default=[]) or []
        parameters = [ParameterModel.from_mapping(p) for p in raw_params]

        return cls(
            name=name,
            intent_id=intent_id,
            speech_response=speech_response,
            user_defined=user_defined,
            api_trigger=api_trigger,
            api_details=api_details,
            parameters=parameters,
        )

    # Backwards compatible alias
    from_db = from_mapping


class ChatModel:
    """Mutable runtime chat state used by the dialogue manager.

    Kept mutable on purpose because conversations evolve during handling. Types
    are annotated and defaults are safer (no shared mutable defaults).
    """

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
        self.input_text: str = input_text
        self.context: Dict[str, Any] = context or {}
        self.intent: Dict[str, Any] = intent or {}
        self.nlu: Dict[str, Any] = {}
        self.extracted_parameters: Dict[str, Any] = extracted_parameters or {}
        self.missing_parameters: List[str] = missing_parameters or []
        self.complete: bool = complete
        self.speech_response: List[str] = speech_response or []
        self.current_node: str = current_node
        self.parameters: List[Dict[str, Any]] = parameters or []
        self.owner: str = owner
        self.date: str = date or datetime.now(timezone.utc).isoformat()

    @classmethod
    def from_json(cls, request_json: Dict[str, Any]) -> "ChatModel":
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
        """Reset the transient conversational state."""
        self.complete = False
        self.intent = {}
        self.missing_parameters = []
        self.extracted_parameters = {}
        self.parameters = []
        self.current_node = ""
        self.speech_response = []


class UserMessage:
    """Simple value object representing an inbound user message."""

    def __init__(
        self,
        thread_id: str,
        text: str,
        context: Dict[str, Any],
        channel: str = "rest",
    ) -> None:
        self.thread_id: str = thread_id
        self.text: str = text
        self.channel: str = channel
        self.context: Dict[str, Any] = context

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
            context=data["context"],
            channel=data.get("channel", "rest"),
        )