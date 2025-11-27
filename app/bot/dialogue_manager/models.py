from typing import Optional, Dict, List, Any, Text
from datetime import datetime, UTC
from copy import deepcopy
from dataclasses import dataclass, field
from app.admin.intents.schemas import Intent


@dataclass
class ApiDetailsModel:
    """Model for API trigger details."""
    url: str
    request_type: str
    headers: List[Dict[str, str]]
    is_json: bool = False
    json_data: str = "{}"

    def get_headers(self) -> Dict[str, str]:
        """Extract headers from list format to dictionary format."""
        headers = {}
        for header in self.headers:
            headers[header["headerKey"]] = header["headerValue"]
        return headers


@dataclass
class ParameterModel:
    """Model for intent parameters."""
    name: str
    required: bool = False
    type: Optional[str] = None
    prompt: Optional[str] = None


@dataclass
class IntentModel:
    """Domain model for dialogue intents with database mapping."""
    name: str
    intent_id: str
    speech_response: str
    user_defined: bool = True
    api_trigger: bool = False
    api_details: Optional[ApiDetailsModel] = None
    parameters: List[ParameterModel] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate and initialize parameters."""
        if self.parameters is None:
            self.parameters = []

    @classmethod
    def from_db(cls, db_intent: Intent) -> "IntentModel":
        """Convert database Intent model to domain Intent model with error handling.
        
        Args:
            db_intent: Database Intent model instance
            
        Returns:
            IntentModel: Domain model instance
            
        Raises:
            ValueError: If required fields are missing or invalid
        """
        if not db_intent:
            raise ValueError("Database intent cannot be None")
        
        if not hasattr(db_intent, 'name') or not db_intent.name:
            raise ValueError("Intent name is required")
        
        if not hasattr(db_intent, 'intentId') or not db_intent.intentId:
            raise ValueError("Intent ID is required")
        
        api_details = None
        try:
            if hasattr(db_intent, 'apiDetails') and db_intent.apiDetails:
                api_details = ApiDetailsModel(
                    url=getattr(db_intent.apiDetails, 'url', ''),
                    request_type=getattr(db_intent.apiDetails, 'requestType', ''),
                    headers=getattr(db_intent.apiDetails, 'headers', []),
                    is_json=getattr(db_intent.apiDetails, 'isJson', False),
                    json_data=getattr(db_intent.apiDetails, 'jsonData', '{}'),
                )
        except (AttributeError, TypeError) as e:
            raise ValueError(f"Invalid API details structure: {str(e)}")

        parameters = []
        try:
            if hasattr(db_intent, 'parameters') and db_intent.parameters:
                parameters = [
                    ParameterModel(
                        name=getattr(p, 'name', ''),
                        required=getattr(p, 'required', False),
                        type=getattr(p, 'type', None),
                        prompt=getattr(p, 'prompt', None),
                    )
                    for p in db_intent.parameters
                ]
        except (AttributeError, TypeError) as e:
            raise ValueError(f"Invalid parameters structure: {str(e)}")

        return cls(
            name=db_intent.name,
            intent_id=db_intent.intentId,
            speech_response=getattr(db_intent, 'speechResponse', ''),
            user_defined=getattr(db_intent, 'userDefined', True),
            api_trigger=getattr(db_intent, 'apiTrigger', False),
            api_details=api_details,
            parameters=parameters,
        )


class ChatModelBuilder:
    """Builder pattern for constructing ChatModel instances."""
    
    def __init__(self, input_text: str) -> None:
        """Initialize builder with required input text.
        
        Args:
            input_text: User input text
        """
        self.input_text = input_text
        self.context: Dict = {}
        self.intent: Dict = {}
        self.extracted_parameters: Dict = {}
        self.missing_parameters: List[str] = []
        self.complete: bool = False
        self.speech_response: List[str] = []
        self.current_node: str = ""
        self.parameters: List[Dict[str, Any]] = []
        self.owner: str = ""
        self.date: Optional[str] = None

    def with_context(self, context: Dict) -> "ChatModelBuilder":
        """Set context."""
        self.context = context or {}
        return self

    def with_intent(self, intent: Dict) -> "ChatModelBuilder":
        """Set intent."""
        self.intent = intent or {}
        return self

    def with_extracted_parameters(self, params: Dict) -> "ChatModelBuilder":
        """Set extracted parameters."""
        self.extracted_parameters = params or {}
        return self

    def with_missing_parameters(self, params: List[str]) -> "ChatModelBuilder":
        """Set missing parameters."""
        self.missing_parameters = params or []
        return self

    def with_complete(self, complete: bool) -> "ChatModelBuilder":
        """Set completion status."""
        self.complete = complete
        return self

    def with_speech_response(self, response: List[str]) -> "ChatModelBuilder":
        """Set speech response."""
        self.speech_response = response or []
        return self

    def with_current_node(self, node: str) -> "ChatModelBuilder":
        """Set current node."""
        self.current_node = node or ""
        return self

    def with_parameters(self, params: List[Dict[str, Any]]) -> "ChatModelBuilder":
        """Set parameters."""
        self.parameters = params or []
        return self

    def with_owner(self, owner: str) -> "ChatModelBuilder":
        """Set owner."""
        self.owner = owner or ""
        return self

    def with_date(self, date: Optional[str]) -> "ChatModelBuilder":
        """Set date."""
        self.date = date
        return self

    def build(self) -> "ChatModel":
        """Build ChatModel instance."""
        return ChatModel(
            input_text=self.input_text,
            context=self.context,
            intent=self.intent,
            extracted_parameters=self.extracted_parameters,
            missing_parameters=self.missing_parameters,
            complete=self.complete,
            speech_response=self.speech_response,
            current_node=self.current_node,
            parameters=self.parameters,
            owner=self.owner,
            date=self.date,
        )


class ChatModel:
    """Core dialogue chat model for managing conversation state."""
    
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
    ) -> None:
        """Initialize ChatModel with conversation state.
        
        Args:
            input_text: User input text
            context: Conversation context dictionary
            intent: Detected intent dictionary
            extracted_parameters: Extracted parameters from user input
            missing_parameters: List of missing required parameters
            complete: Whether dialogue is complete
            speech_response: List of speech responses
            current_node: Current dialogue node identifier
            parameters: List of parameter dictionaries
            owner: Owner/user identifier
            date: ISO format timestamp
        """
        self.input_text = input_text
        self.context = context or {}
        self.intent = intent or {}
        self.nlu: Dict = {}
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
        """Create ChatModel from JSON with validation.
        
        Args:
            request_json: JSON dictionary with chat data
            
        Returns:
            ChatModel: Instance created from JSON
            
        Raises:
            ValueError: If required fields are missing or invalid
        """
        if not isinstance(request_json, dict):
            raise ValueError("Request JSON must be a dictionary")
        
        input_text = request_json.get("input", "")
        if not isinstance(input_text, str):
            raise ValueError("Input text must be a string")
        
        # Validate collection types
        context = request_json.get("context", {})
        if not isinstance(context, dict):
            raise ValueError("Context must be a dictionary")
        
        intent = request_json.get("intent", {})
        if not isinstance(intent, dict):
            raise ValueError("Intent must be a dictionary")
        
        extracted_parameters = request_json.get("extractedParameters", {})
        if not isinstance(extracted_parameters, dict):
            raise ValueError("Extracted parameters must be a dictionary")
        
        missing_parameters = request_json.get("missingParameters", [])
        if not isinstance(missing_parameters, list):
            raise ValueError("Missing parameters must be a list")
        
        speech_response = request_json.get("speechResponse", [])
        if not isinstance(speech_response, list):
            raise ValueError("Speech response must be a list")
        
        parameters = request_json.get("parameters", [])
        if not isinstance(parameters, list):
            raise ValueError("Parameters must be a list")
        
        return cls(
            input_text=input_text,
            context=context,
            intent=intent,
            extracted_parameters=extracted_parameters,
            missing_parameters=missing_parameters,
            complete=request_json.get("complete", False),
            speech_response=speech_response,
            current_node=request_json.get("currentNode", ""),
            parameters=parameters,
            owner=request_json.get("owner", ""),
            date=request_json.get("date", None),
        )

    def to_json(self) -> Dict:
        """Convert ChatModel to JSON dictionary.
        
        Returns:
            Dict: JSON-serializable dictionary representation
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
            ChatModel: Cloned instance
        """
        return deepcopy(self)

    def reset(self) -> None:
        """Reset dialogue state to initial values with correct types."""
        self.complete = False
        self.intent = {}
        self.missing_parameters = []
        self.extracted_parameters = {}
        self.parameters = []
        self.current_node = ""
        self.speech_response = []


class UserMessage:
    """Model for user messages in dialogue."""
    
    def __init__(
        self, thread_id: str, text: Text, context: Dict, channel: Text = "rest"
    ) -> None:
        """Initialize UserMessage.
        
        Args:
            thread_id: Unique thread identifier
            text: Message text content
            context: Message context dictionary
            channel: Communication channel (default: "rest")
        """
        self.thread_id = thread_id
        self.text = text
        self.channel = channel
        self.context = context

    def to_dict(self) -> Dict:
        """Convert UserMessage to dictionary.
        
        Returns:
            Dict: Dictionary representation
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
            UserMessage: Instance created from dictionary
        """
        return cls(
            thread_id=data["thread_id"],
            text=data["text"],
            context=data["context"],
            channel=data.get("channel", "rest"),
        )