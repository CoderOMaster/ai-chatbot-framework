from typing import Optional, Dict, List, Any, Text
from datetime import datetime, UTC
from shared.models.dialogue import UserMessage


class State:
    """State model for conversation persistence.
    
    Attributes:
        thread_id: Conversation thread identifier
        user_message: Current user message
        bot_message: Bot response messages
        nlu: Natural language understanding results
        context: Contextual information
        intent: Detected intent
        parameters: List of parameters
        extracted_parameters: Parameters extracted from user input
        missing_parameters: Parameters still needed from user
        complete: Whether the intent is complete
        current_node: Current dialogue node
        date: Timestamp of the state
    """
    
    def __init__(
        self,
        thread_id: Text,
        user_message: Optional[UserMessage] = None,
        bot_message: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        intent: Optional[Dict[str, Any]] = None,
        parameters: Optional[List[Dict[str, Any]]] = None,
        extracted_parameters: Optional[Dict[str, Any]] = None,
        missing_parameters: Optional[List[str]] = None,
        complete: bool = False,
        current_node: Optional[Text] = None,
        date: Optional[datetime] = None,
    ) -> None:
        """Initialize State.
        
        Args:
            thread_id: Conversation thread identifier
            user_message: Current user message
            bot_message: Bot response messages
            context: Contextual information
            intent: Detected intent
            parameters: List of parameters
            extracted_parameters: Parameters extracted from user input
            missing_parameters: Parameters still needed from user
            complete: Whether the intent is complete
            current_node: Current dialogue node
            date: Timestamp of the state
        """
        self.thread_id: Text = thread_id
        self.user_message: Optional[UserMessage] = user_message
        self.bot_message: List[Dict[str, Any]] = bot_message or []
        self.nlu: Dict[str, Any] = {}
        self.context: Dict[str, Any] = context or {}
        self.intent: Dict[str, Any] = intent or {}
        self.parameters: List[Dict[str, Any]] = parameters or []
        self.extracted_parameters: Dict[str, Any] = extracted_parameters or {}
        self.missing_parameters: List[str] = missing_parameters or []
        self.complete: bool = complete
        self.current_node: Optional[Text] = current_node
        self.date: datetime = date or datetime.now(UTC)

    def to_dict(self) -> Dict[str, Any]:
        """Convert State to dictionary.
        
        Returns:
            Dictionary representation of State
        """
        return {
            "thread_id": self.thread_id,
            "user_message": self.user_message.to_dict() if self.user_message else None,
            "bot_message": self.bot_message,
            "nlu": self.nlu,
            "context": self.context,
            "intent": self.intent,
            "parameters": self.parameters,
            "extracted_parameters": self.extracted_parameters,
            "missing_parameters": self.missing_parameters,
            "complete": self.complete,
            "current_node": self.current_node,
            "date": self.date,
        }

    @classmethod
    def from_dict(cls, state_dict: Dict[str, Any]) -> "State":
        """Create State from dictionary with validation.
        
        Args:
            state_dict: Dictionary with state data
            
        Returns:
            State instance
            
        Raises:
            KeyError: If required keys are missing
        """
        # Validate required keys
        required_keys = {
            "thread_id",
            "context",
            "intent",
            "parameters",
            "extracted_parameters",
            "missing_parameters",
            "complete",
            "current_node",
        }
        missing_keys = required_keys - set(state_dict.keys())
        if missing_keys:
            raise KeyError(f"Missing required keys in state_dict: {missing_keys}")
        
        # Parse user_message if present
        user_message: Optional[UserMessage] = None
        if state_dict.get("user_message"):
            user_message = UserMessage.from_dict(state_dict["user_message"])
        
        return cls(
            thread_id=state_dict["thread_id"],
            user_message=user_message,
            bot_message=state_dict.get("bot_message"),
            context=state_dict["context"],
            intent=state_dict["intent"],
            parameters=state_dict["parameters"],
            extracted_parameters=state_dict["extracted_parameters"],
            missing_parameters=state_dict["missing_parameters"],
            complete=state_dict["complete"],
            current_node=state_dict["current_node"],
            date=state_dict.get("date"),
        )

    def update(self, user_message: UserMessage) -> None:
        """Update state with new user message.
        
        Args:
            user_message: New user message
        """
        self.user_message = user_message
        self.date = datetime.now(UTC)
        self.context.update(user_message.context)

        if self.complete:
            self.bot_message = []
            self.intent = {}
            self.parameters = []
            self.extracted_parameters = {}
            self.missing_parameters = []
            self.complete = False
            self.current_node = None

    def get_active_intent_id(self) -> Optional[str]:
        """Get the active intent ID.
        
        Returns:
            Intent ID if intent exists, None otherwise
        """
        if self.intent:
            return self.intent.get("id")
        return None