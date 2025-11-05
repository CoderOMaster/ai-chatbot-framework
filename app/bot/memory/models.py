from typing import Optional, Dict, List, Any, Text
from datetime import datetime, timezone
from app.bot.dialogue_manager.models import UserMessage


class State:
    """Data transfer object representing a conversation state.

    Keep this DTO stable — consumers persist and rely on the shape.
    If you need to change it, bump the package version and provide
    migration helpers.
    """

    def __init__(
        self,
        thread_id: Text,
        user_message: Optional[UserMessage] = None,
        bot_message: Optional[List[Dict]] = None,
        context: Optional[Dict] = None,
        intent: Optional[Dict] = None,
        parameters: Optional[List[Dict[str, Any]]] = None,
        extracted_parameters: Optional[Dict] = None,
        missing_parameters: Optional[List[str]] = None,
        complete: bool = False,
        current_node: Text = "",
        date: Optional[datetime] = None,
    ):
        self.thread_id = thread_id
        self.user_message = user_message
        self.bot_message = bot_message
        self.nlu = {}
        self.context = context or {}
        self.intent = intent or {}
        self.parameters = parameters or []
        self.extracted_parameters = extracted_parameters or {}
        self.missing_parameters = missing_parameters or []
        self.complete = complete
        self.current_node = current_node
        # use timezone-aware UTC timestamps
        self.date = date or datetime.now(timezone.utc)

    def to_dict(self) -> Dict:
        """Serialize State to a plain dictionary suitable for storage.

        Note: user_message is expected to implement to_dict() in its
        module.
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
    def from_dict(cls, state_dict: Dict) -> "State":
        """Create a State instance from a dictionary (e.g. from DB)."""
        # parse all the fields
        return cls(
            thread_id=state_dict["thread_id"],
            context=state_dict.get("context", {}),
            intent=state_dict.get("intent", {}),
            parameters=state_dict.get("parameters", []),
            extracted_parameters=state_dict.get("extracted_parameters", {}),
            missing_parameters=state_dict.get("missing_parameters", []),
            complete=state_dict.get("complete", False),
            current_node=state_dict.get("current_node", ""),
            date=state_dict.get("date"),
        )

    def update(self, user_message: UserMessage):
        """Update the state with a new user message."""
        self.user_message = user_message
        self.date = datetime.now(timezone.utc)
        self.context.update(user_message.context)

        if self.complete:
            self.bot_message = []
            self.intent = None
            self.parameters = []
            self.extracted_parameters = {}
            self.missing_parameters = []
            self.complete = False
            self.current_node = None

    def get_active_intent_id(self):
        """Return the active intent id if present."""
        if self.intent:
            return self.intent.get("id")
        return None