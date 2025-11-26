from typing import Optional, Dict, List, Any, Text
from datetime import datetime, UTC
from copy import deepcopy
from dataclasses import dataclass
from app.admin.intents.schemas import Intent


@dataclass
class ApiDetailsModel:
    """Runtime model for API trigger configuration.
    
    Represents API endpoint details used by the dialogue manager to invoke
    external services when an intent is triggered.
    """
    url: str
    request_type: str
    headers: List[Dict[str, str]]
    is_json: bool = False
    json_data: str = "{}"

    def get_headers(self) -> Dict[str, str]:
        """Convert header list to dictionary format.
        
        Returns:
            Dictionary mapping header keys to values
        """
        headers = {}
        for header in self.headers:
            headers[header["headerKey"]] = header["headerValue"]
        return headers


@dataclass
class ParameterModel:
    """Runtime model for intent parameters.
    
    Represents a parameter (slot/entity) that can be extracted from user input
    during dialogue execution.
    """
    name: str
    required: bool = False
    type: Optional[str] = None
    prompt: Optional[str] = None


@dataclass
class IntentModel:
    """Runtime model for dialogue intents.
    
    Represents the runtime state of an intent, converted from the database schema.
    Includes defensive checks to handle missing or legacy fields gracefully.
    """
    name: str
    intent_id: str
    speech_response: str
    user_defined: bool = True
    api_trigger: bool = False
    api_details: Optional[ApiDetailsModel] = None
    parameters: List[ParameterModel] = None

    def __post_init__(self):
        """Initialize default values for mutable fields."""
        if self.parameters is None:
            self.parameters = []

    @classmethod
    def from_db(cls, db_intent: Intent) -> "IntentModel":
        """Convert database Intent model to runtime IntentModel.
        
        Includes defensive checks to handle missing or legacy fields:
        - Validates required fields (name, intentId, speechResponse)
        - Safely handles optional apiDetails and parameters
        - Provides sensible defaults for missing fields
        
        Args:
            db_intent: Database Intent schema instance
            
        Returns:
            IntentModel instance ready for runtime use
            
        Raises:
            AttributeError: If required fields are missing
        """
        # Defensive check for required fields
        if not hasattr(db_intent, 'name') or not db_intent.name:
            raise AttributeError("Intent missing required field: name")
        if not hasattr(db_intent, 'intentId') or not db_intent.intentId:
            raise AttributeError("Intent missing required field: intentId")
        if not hasattr(db_intent, 'speechResponse') or not db_intent.speechResponse:
            raise AttributeError("Intent missing required field: speechResponse")
        
        # Safely handle optional apiDetails
        api_details = None
        if hasattr(db_intent, 'apiDetails') and db_intent.apiDetails:
            try:
                api_details = ApiDetailsModel(
                    url=getattr(db_intent.apiDetails, 'url', ''),
                    request_type=getattr(db_intent.apiDetails, 'requestType', 'GET'),
                    headers=getattr(db_intent.apiDetails, 'headers', []),
                    is_json=getattr(db_intent.apiDetails, 'isJson', False),
                    json_data=getattr(db_intent.apiDetails, 'jsonData', '{}'),
                )
            except (AttributeError, TypeError):
                # Legacy or malformed apiDetails - skip gracefully
                api_details = None

        # Safely handle optional parameters
        parameters = []
        if hasattr(db_intent, 'parameters') and db_intent.parameters:
            try:
                parameters = [
                    ParameterModel(
                        name=getattr(p, 'name', ''),
                        required=getattr(p, 'required', False),
                        type=getattr(p, 'type', None),
                        prompt=getattr(p, 'prompt', None),
                    )
                    for p in db_intent.parameters
                    if hasattr(p, 'name') and p.name  # Skip malformed parameters
                ]
            except (AttributeError, TypeError):
                # Legacy or malformed parameters - skip gracefully
                parameters = []

        return cls(
            name=db_intent.name,
            intent_id=db_intent.intentId,
            speech_response=db_intent.speechResponse,
            user_defined=getattr(db_intent, 'userDefined', True),
            api_trigger=getattr(db_intent, 'apiTrigger', False),
            api_details=api_details,
            parameters=parameters,
        )


class ChatModel:
    """Runtime model for dialogue chat state.
    
    Maintains the complete state of an ongoing dialogue session, including
    user input, extracted parameters, intent resolution, and responses.
    """
    
    def __init__(
        self,
        input_text: str,
        context: Optional[Dict] = None,
        intent: Optional[Dict] = None,
        extracted_parameters: Optional[Dict] = None,
        missing_parameters: Optional[List[str]] = None,
        complete: bool = False,
        speech_response: Optional[List[str]] = None,
        current_node: str = "",
        parameters: Optional[List[Dict[str, Any]]] = None,
        owner: str = "",
        date: Optional[str] = None,
    ):
        """Initialize ChatModel with dialogue state.
        
        Args:
            input_text: User's input text
            context: Dialogue context dictionary
            intent: Resolved intent information
            extracted_parameters: Parameters extracted from user input
            missing_parameters: Required parameters not yet provided
            complete: Whether the intent execution is complete
            speech_response: Bot's response messages
            current_node: Current dialogue flow node
            parameters: Intent parameters definition
            owner: User/session owner identifier
            date: Timestamp of the message (defaults to current UTC time)
        """
        self.input_text = input_text
        self.context = context or {}
        self.intent = intent or {}
        self.nlu = {}
        self.extracted_parameters = extracted_parameters or {}
        self.missing_parameters = missing_parameters or []
        self.complete = complete
        self.speech_response = speech_response or []
        self.current_node = current_node
        self.parameters = parameters or []
        self.owner = owner
        self.date = date or datetime.now(UTC).isoformat()

    @classmethod
    def from_json(cls, request_json: Dict) -> "ChatModel":
        """Create ChatModel from JSON request.
        
        Args:
            request_json: JSON dictionary with chat state
            
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

    def to_json(self) -> Dict:
        """Convert ChatModel to JSON dictionary.
        
        Returns:
            Dictionary representation of chat state
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
        """Create a deep copy of this ChatModel.
        
        Returns:
            Independent copy of the chat state
        """
        return deepcopy(self)

    def reset(self) -> None:
        """Reset dialogue state to initial values."""
        self.complete = False
        self.intent = {}
        self.missing_parameters = []
        self.extracted_parameters = {}
        self.parameters = []
        self.current_node = {}
        self.speech_response = {}


class UserMessage:
    """Runtime model for user messages.
    
    Represents a user message in a dialogue session with thread context
    and channel information.
    """
    
    def __init__(
        self, thread_id: str, text: Text, context: Dict, channel: Text = "rest"
    ):
        """Initialize UserMessage.
        
        Args:
            thread_id: Unique identifier for the conversation thread
            text: User's message text
            context: Dialogue context dictionary
            channel: Communication channel (default: "rest")
        """
        self.thread_id = thread_id
        self.text = text
        self.channel = channel
        self.context = context

    def to_dict(self) -> Dict:
        """Convert UserMessage to dictionary.
        
        Returns:
            Dictionary representation of the message
        """
        return {
            "thread_id": self.thread_id,
            "text": self.text,
            "channel": self.channel,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "UserMessage":
        """Create UserMessage from dictionary.
        
        Args:
            data: Dictionary with message data
            
        Returns:
            UserMessage instance
        """
        return cls(
            thread_id=data["thread_id"],
            text=data["text"],
            context=data["context"],
            channel=data.get("channel", "rest"),
        )