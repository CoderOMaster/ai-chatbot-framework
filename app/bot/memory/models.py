from typing import Optional, Dict, List, Any, Text
from datetime import datetime, UTC
from dataclasses import dataclass, field, replace
from app.bot.dialogue_manager.models import UserMessage


class StateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class StateValidationError(Exception):
    """Raised when state data fails validation."""
    pass


@dataclass(frozen=True)
class State:
    """Immutable conversation state model with versioning and validation.
    
    Attributes:
        thread_id: Unique conversation thread identifier
        user_message: Current user message object
        bot_message: Bot response messages
        context: Conversation context data
        intent: Detected intent information
        parameters: Parameter definitions
        extracted_parameters: Extracted parameter values
        missing_parameters: Required parameters not yet provided
        complete: Whether the intent is complete
        current_node: Current dialogue node
        date: Timestamp of state creation/update
        version: State schema version for backwards compatibility
    """
    thread_id: Text
    user_message: Optional[UserMessage] = None
    bot_message: Optional[List[Dict]] = None
    context: Dict = field(default_factory=dict)
    intent: Dict = field(default_factory=dict)
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    extracted_parameters: Dict = field(default_factory=dict)
    missing_parameters: List[str] = field(default_factory=list)
    complete: bool = False
    current_node: Text = ""
    date: Optional[datetime] = None
    nlu: Dict = field(default_factory=dict)
    version: int = 1

    def __post_init__(self):
        """Validate state after initialization."""
        if not self.thread_id:
            raise StateValidationError("thread_id cannot be empty")
        
        # Set default date if not provided
        if self.date is None:
            object.__setattr__(self, 'date', datetime.now(UTC))

    def to_dict(self) -> Dict:
        """Convert state to dictionary representation.
        
        Returns:
            Dictionary representation of the state with all fields serialized.
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
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, state_dict: Dict) -> "State":
        """Create State instance from dictionary with validation.
        
        Args:
            state_dict: Dictionary containing state data
            
        Returns:
            New State instance
            
        Raises:
            StateValidationError: If required fields are missing or invalid
        """
        required_fields = ["thread_id"]
        missing_fields = [f for f in required_fields if f not in state_dict]
        
        if missing_fields:
            raise StateValidationError(
                f"Missing required fields in state_dict: {missing_fields}"
            )
        
        try:
            user_message = None
            if state_dict.get("user_message"):
                user_message = UserMessage.from_dict(state_dict["user_message"])
            
            return cls(
                thread_id=state_dict["thread_id"],
                user_message=user_message,
                bot_message=state_dict.get("bot_message"),
                context=state_dict.get("context", {}),
                intent=state_dict.get("intent", {}),
                parameters=state_dict.get("parameters", []),
                extracted_parameters=state_dict.get("extracted_parameters", {}),
                missing_parameters=state_dict.get("missing_parameters", []),
                complete=state_dict.get("complete", False),
                current_node=state_dict.get("current_node", ""),
                date=state_dict.get("date"),
                nlu=state_dict.get("nlu", {}),
                version=state_dict.get("version", 1),
            )
        except (KeyError, TypeError, ValueError) as e:
            raise StateValidationError(
                f"Failed to deserialize state from dictionary: {str(e)}"
            ) from e

    def update(self, user_message: UserMessage) -> "State":
        """Create a new state with updated user message and reset completion state.
        
        Args:
            user_message: New user message to process
            
        Returns:
            New State instance with updated values
            
        Raises:
            StateTransitionError: If state transition is invalid
        """
        if not isinstance(user_message, UserMessage):
            raise StateTransitionError(
                f"user_message must be UserMessage instance, got {type(user_message)}"
            )
        
        # Validate transition: can only update if we have a valid thread_id
        if not self.thread_id:
            raise StateTransitionError("Cannot update state without valid thread_id")
        
        # Create new state with updated values
        new_context = {**self.context}
        if hasattr(user_message, 'context') and user_message.context:
            new_context.update(user_message.context)
        
        # Reset completion-related fields if transitioning from complete state
        new_bot_message = self.bot_message
        new_intent = self.intent
        new_parameters = self.parameters
        new_extracted_parameters = self.extracted_parameters
        new_missing_parameters = self.missing_parameters
        new_complete = self.complete
        new_current_node = self.current_node
        
        if self.complete:
            new_bot_message = []
            new_intent = {}
            new_parameters = []
            new_extracted_parameters = {}
            new_missing_parameters = []
            new_complete = False
            new_current_node = ""
        
        return replace(
            self,
            user_message=user_message,
            date=datetime.now(UTC),
            context=new_context,
            bot_message=new_bot_message,
            intent=new_intent,
            parameters=new_parameters,
            extracted_parameters=new_extracted_parameters,
            missing_parameters=new_missing_parameters,
            complete=new_complete,
            current_node=new_current_node,
        )

    def get_active_intent_id(self) -> Optional[str]:
        """Get the ID of the currently active intent.
        
        Returns:
            Intent ID if intent is active, None otherwise
        """
        if self.intent:
            return self.intent.get("id")
        return None