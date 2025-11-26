from typing import Optional, Dict, List, Any, Text
from datetime import datetime, UTC
from copy import deepcopy
from dataclasses import dataclass, field
from shared.models.intents import Intent


@dataclass
class ApiDetailsModel:
    """Model for API details configuration.
    
    Attributes:
        url: API endpoint URL
        request_type: HTTP method (GET, POST, PUT, DELETE, etc.)
        headers: List of header dictionaries
        is_json: Whether request body is JSON
        json_data: JSON request body as string
    """
    url: str
    request_type: str
    headers: List[Dict[str, str]]
    is_json: bool = False
    json_data: str = "{}"

    def get_headers(self) -> Dict[str, str]:
        """Convert headers list to dictionary format with defensive null checks.
        
        Returns:
            Dictionary mapping header keys to values
        """
        headers: Dict[str, str] = {}
        if not self.headers:
            return headers
        
        for header in self.headers:
            if header and isinstance(header, dict):
                header_key = header.get("headerKey")
                header_value = header.get("headerValue")
                if header_key and header_value:
                    headers[header_key] = header_value
        return headers


@dataclass
class ParameterModel:
    """Model for intent parameters.
    
    Attributes:
        name: Parameter name
        required: Whether the parameter is required
        type: Parameter data type
        prompt: Prompt text to request the parameter from user
    """
    name: str
    required: bool = False
    type: Optional[str] = None
    prompt: Optional[str] = None


@dataclass
class IntentModel:
    """Domain model for intents.
    
    Attributes:
        name: Intent name
        intent_id: Unique string identifier for the intent
        speech_response: Response text to return to user
        user_defined: Whether intent was created by user
        api_trigger: Whether this intent triggers an API call
        api_details: API configuration if api_trigger is True
        parameters: List of parameters the intent can extract
    """
    name: str
    intent_id: str
    speech_response: str
    user_defined: bool = True
    api_trigger: bool = False
    api_details: Optional[ApiDetailsModel] = None
    parameters: List[ParameterModel] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Initialize parameters list if None."""
        if self.parameters is None:
            self.parameters = []

    @classmethod
    def from_db(cls, db_intent: Intent) -> "IntentModel":
        """Convert database Intent model to domain Intent model.
        
        Args:
            db_intent: Database Intent model
            
        Returns:
            IntentModel instance
        """
        api_details: Optional[ApiDetailsModel] = None
        if db_intent.apiDetails:
            api_details = ApiDetailsModel(
                url=db_intent.apiDetails.url or "",
                request_type=db_intent.apiDetails.requestType or "",
                headers=db_intent.apiDetails.headers or [],
                is_json=db_intent.apiDetails.isJson or False,
                json_data=db_intent.apiDetails.jsonData or "{}",
            )

        parameters: List[ParameterModel] = []
        if db_intent.parameters:
            parameters = [
                ParameterModel(
                    name=p.name,
                    required=p.required or False,
                    type=p.type,
                    prompt=p.prompt,
                )
                for p in db_intent.parameters
                if p is not None
            ]

        return cls(
            name=db_intent.name or "",
            intent_id=db_intent.intentId or "",
            speech_response=db_intent.speechResponse or "",
            user_defined=db_intent.userDefined or True,
            api_trigger=db_intent.apiTrigger or False,
            api_details=api_details,
            parameters=parameters,
        )


class ChatModel:
    """Model for chat interactions.
    
    Attributes:
        input_text: User input text
        context: Contextual information
        intent: Detected intent
        extracted_parameters: Parameters extracted from user input
        missing_parameters: Parameters still needed from user
        complete: Whether the intent is complete
        speech_response: List of response texts
        current_node: Current dialogue node
        parameters: List of parameter dictionaries
        owner: Owner/user identifier
        date: Timestamp of the message
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
        """Initialize ChatModel.
        
        Args:
            input_text: User input text
            context: Contextual information
            intent: Detected intent
            extracted_parameters: Parameters extracted from user input
            missing_parameters: Parameters still needed from user
            complete: Whether the intent is complete
            speech_response: List of response texts
            current_node: Current dialogue node
            parameters: List of parameter dictionaries
            owner: Owner/user identifier
            date: Timestamp of the message
        """
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
        self.date: str = date or datetime.now(UTC).isoformat()

    @classmethod
    def from_json(cls, request_json: Dict[str, Any]) -> "ChatModel":
        """Create ChatModel from JSON dictionary.
        
        Args:
            request_json: JSON dictionary with chat data
            
        Returns:
            ChatModel instance
        """
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
        """Convert ChatModel to JSON dictionary.
        
        Returns:
            Dictionary representation of ChatModel
        """
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
        """Create a deep copy of the ChatModel.
        
        Returns:
            Deep copy of ChatModel
        """
        return deepcopy(self)

    def reset(self) -> None:
        """Reset chat state to initial values."""
        self.complete = False
        self.intent = {}
        self.missing_parameters = []
        self.extracted_parameters = {}
        self.parameters = []
        self.current_node = ""
        self.speech_response = []


class UserMessage:
    """Model for user messages.
    
    Attributes:
        thread_id: Conversation thread identifier
        text: Message text
        channel: Communication channel (e.g., 'rest', 'slack')
        context: Contextual information
    """
    
    def __init__(
        self, 
        thread_id: str, 
        text: Text, 
        context: Dict[str, Any], 
        channel: Text = "rest"
    ) -> None:
        """Initialize UserMessage.
        
        Args:
            thread_id: Conversation thread identifier
            text: Message text
            context: Contextual information
            channel: Communication channel
        """
        self.thread_id: str = thread_id
        self.text: Text = text
        self.channel: Text = channel
        self.context: Dict[str, Any] = context

    def to_dict(self) -> Dict[str, Any]:
        """Convert UserMessage to dictionary.
        
        Returns:
            Dictionary representation of UserMessage
        """
        return {
            "thread_id": self.thread_id,
            "text": self.text,
            "channel": self.channel,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserMessage":
        """Create UserMessage from dictionary.
        
        Args:
            data: Dictionary with user message data
            
        Returns:
            UserMessage instance
        """
        return cls(
            thread_id=data["thread_id"],
            text=data["text"],
            context=data["context"],
            channel=data.get("channel", "rest"),
        )