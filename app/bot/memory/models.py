"""Memory models for dialogue state management.

This module defines the data models used to represent and persist conversation state
in the dialogue management system. The State model is the primary DTO for storing
conversation context, intents, parameters, and dialogue flow information.
"""

from typing import Optional, Dict, List, Any
from datetime import datetime, UTC
from pydantic import BaseModel, Field, validator
from app.bot.dialogue_manager.models import UserMessage


class State(BaseModel):
    """Represents the complete state of a conversation thread.
    
    This model encapsulates all information related to an ongoing conversation,
    including user messages, bot responses, extracted intents, parameters, and
    dialogue context. It serves as the primary data transfer object (DTO) for
    persisting conversation state to the database.
    
    **Persisted Fields** (stored in database):
        - thread_id: Unique identifier for the conversation thread
        - context: Dictionary of contextual information
        - intent: Dictionary representing the detected intent
        - parameters: List of parameter definitions
        - extracted_parameters: Dictionary of extracted parameters
        - missing_parameters: List of required parameter names
        - complete: Boolean flag for intent completion
        - current_node: Identifier of current dialogue node
        - date: Timestamp of last state update
    
    **Transient Fields** (runtime-only, not persisted):
        - user_message: Current user message object (reconstructed on load)
        - bot_message: List of bot response messages (session-specific)
        - nlu: Dictionary of NLU processing results (session-specific)
    
    Attributes:
        thread_id: Unique identifier for the conversation thread.
        user_message: The current user message object containing text and context.
        bot_message: List of bot response messages for the current turn.
        context: Dictionary of contextual information accumulated during the conversation.
        intent: Dictionary representing the detected intent with metadata.
        parameters: List of parameter definitions for the current intent.
        extracted_parameters: Dictionary of parameters extracted from user input.
        missing_parameters: List of parameter names still required from the user.
        complete: Boolean flag indicating if the current intent is complete.
        current_node: Identifier of the current dialogue flow node being executed.
        date: Timestamp of the last state update.
        nlu: Dictionary containing NLU processing results (confidence scores, entities, etc.).
    """
    
    # Persisted fields
    thread_id: str = Field(..., description="Unique identifier for the conversation thread")
    context: Dict[str, Any] = Field(
        default_factory=dict, description="Contextual information accumulated during conversation"
    )
    intent: Dict[str, Any] = Field(
        default_factory=dict, description="Detected intent with metadata"
    )
    parameters: List[Dict[str, Any]] = Field(
        default_factory=list, description="Parameter definitions for current intent"
    )
    extracted_parameters: Dict[str, Any] = Field(
        default_factory=dict, description="Parameters extracted from user input"
    )
    missing_parameters: List[str] = Field(
        default_factory=list, description="Parameter names still required from user"
    )
    complete: bool = Field(
        default=False, description="Flag indicating if current intent is complete"
    )
    current_node: str = Field(
        default="", description="Identifier of current dialogue flow node"
    )
    date: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Timestamp of last state update"
    )
    
    # Transient fields (runtime-only, not persisted)
    user_message: Optional[UserMessage] = Field(
        default=None, description="Current user message object (transient, reconstructed on load)"
    )
    bot_message: Optional[List[Dict]] = Field(
        default=None, description="List of bot response messages (transient, session-specific)"
    )
    nlu: Dict[str, Any] = Field(
        default_factory=dict, description="NLU processing results (transient, session-specific)"
    )

    class Config:
        """Pydantic configuration for State model."""
        arbitrary_types_allowed = True

    @validator("thread_id")
    def validate_thread_id(cls, v: str) -> str:
        """Validate that thread_id is non-empty.
        
        Args:
            v: The thread_id value to validate
            
        Returns:
            The validated thread_id
            
        Raises:
            ValueError: If thread_id is empty or whitespace
        """
        if not v or not v.strip():
            raise ValueError("thread_id cannot be empty")
        return v

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary representation for persistence.
        
        Serializes only the persisted fields to a dictionary format suitable for
        database storage. Transient fields (user_message, bot_message, nlu) are
        excluded as they are reconstructed at runtime.
        
        Returns:
            Dictionary containing persisted state fields with serialized values.
        """
        return {
            "thread_id": self.thread_id,
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
        """Create State instance from dictionary representation with defensive checks.
        
        Deserializes a dictionary (typically from database) into a State object.
        Performs defensive validation on required fields and applies sensible defaults
        for optional fields. Transient fields (user_message, bot_message, nlu) are
        not reconstructed from the dictionary as they are session-specific.
        
        Args:
            state_dict: Dictionary containing persisted state data from database or API.
            
        Returns:
            State instance initialized with values from the dictionary.
            
        Raises:
            ValueError: If required fields are missing or invalid.
            TypeError: If state_dict is not a dictionary.
        """
        # Defensive check: ensure input is a dictionary
        if not isinstance(state_dict, dict):
            raise TypeError(f"Expected dict, got {type(state_dict).__name__}")
        
        # Defensive check: validate required field thread_id
        thread_id = state_dict.get("thread_id")
        if not thread_id or not isinstance(thread_id, str) or not thread_id.strip():
            raise ValueError("thread_id is required and must be a non-empty string")
        
        # Safely extract persisted fields with type validation
        context = state_dict.get("context", {})
        if not isinstance(context, dict):
            context = {}
        
        intent = state_dict.get("intent", {})
        if not isinstance(intent, dict):
            intent = {}
        
        parameters = state_dict.get("parameters", [])
        if not isinstance(parameters, list):
            parameters = []
        
        extracted_parameters = state_dict.get("extracted_parameters", {})
        if not isinstance(extracted_parameters, dict):
            extracted_parameters = {}
        
        missing_parameters = state_dict.get("missing_parameters", [])
        if not isinstance(missing_parameters, list):
            missing_parameters = []
        
        complete = state_dict.get("complete", False)
        if not isinstance(complete, bool):
            complete = False
        
        current_node = state_dict.get("current_node", "")
        if not isinstance(current_node, str):
            current_node = ""
        
        # Handle date field - attempt to parse if string, otherwise use current time
        date = state_dict.get("date")
        if date is None:
            date = datetime.now(UTC)
        elif isinstance(date, str):
            try:
                date = datetime.fromisoformat(date.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                date = datetime.now(UTC)
        elif not isinstance(date, datetime):
            date = datetime.now(UTC)
        
        # Transient fields are not reconstructed from dictionary
        # They will be set to None/empty and populated at runtime
        
        return cls(
            thread_id=thread_id,
            context=context,
            intent=intent,
            parameters=parameters,
            extracted_parameters=extracted_parameters,
            missing_parameters=missing_parameters,
            complete=complete,
            current_node=current_node,
            date=date,
            user_message=None,  # Transient - not persisted
            bot_message=None,   # Transient - not persisted
            nlu={},             # Transient - not persisted
        )

    def update(self, user_message: UserMessage) -> None:
        """Update state with new user message and reset completion state.
        
        Updates the state with a new user message, merges context information,
        and resets the completion state if the previous intent was complete.
        This method is typically called when processing a new user turn.
        
        Args:
            user_message: The new UserMessage object to process.
            
        Raises:
            TypeError: If user_message is not a UserMessage instance.
        """
        if not isinstance(user_message, UserMessage):
            raise TypeError(f"Expected UserMessage, got {type(user_message).__name__}")
        
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
            self.current_node = ""

    def get_active_intent_id(self) -> Optional[str]:
        """Get the ID of the currently active intent.
        
        Retrieves the intent ID from the current intent dictionary if one exists.
        Returns None if no intent is active or if the intent lacks an ID field.
        
        Returns:
            The intent ID string if available, otherwise None.
        """
        if self.intent:
            return self.intent.get("id")
        return None