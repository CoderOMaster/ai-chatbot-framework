from typing import Optional, Dict, List, Any, Text, Union
from datetime import datetime, timezone
from app.bot.dialogue_manager.models import UserMessage


class State:
    """Stable, DB-agnostic representation of a conversation state.

    Notes:
        - user_message is treated as an opaque, serializable object. When
          possible we rehydrate it using UserMessage.from_dict(), but the
          serializer accepts a plain dict as well to avoid tight coupling to
          the dialogue-manager DB schema.
        - to_dict() produces a stable, JSON-friendly representation (dates as
          ISO strings). from_dict() accepts both legacy and newer shapes and
          attempts to coerce types where sensible.
    """

    thread_id: Text
    user_message: Optional[Union[UserMessage, Dict[str, Any]]]
    bot_message: Optional[List[Dict]]
    nlu: Dict[str, Any]
    context: Dict[str, Any]
    intent: Dict[str, Any]
    parameters: List[Dict[str, Any]]
    extracted_parameters: Dict[str, Any]
    missing_parameters: List[str]
    complete: bool
    current_node: Text
    date: datetime

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
    ) -> None:
        self.thread_id = thread_id
        self.user_message = user_message
        self.bot_message = bot_message or []
        self.nlu = {}
        self.context = context or {}
        self.intent = intent or {}
        self.parameters = parameters or []
        self.extracted_parameters = extracted_parameters or {}
        self.missing_parameters = missing_parameters or []
        self.complete = complete
        self.current_node = current_node
        # use timezone-aware utc datetime
        self.date = date or datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        """Return a DB/storage friendly dictionary representation.

        - user_message is returned as a dict if it implements to_dict(), or
          left as-is if already a dict/None.
        - date is serialized to ISO format for portability.
        """
        if hasattr(self.user_message, "to_dict") and not isinstance(
            self.user_message, dict
        ):
            user_message_serialized = self.user_message.to_dict()
        else:
            user_message_serialized = self.user_message

        return {
            "thread_id": self.thread_id,
            "user_message": user_message_serialized,
            "bot_message": self.bot_message,
            "nlu": self.nlu,
            "context": self.context,
            "intent": self.intent,
            "parameters": self.parameters,
            "extracted_parameters": self.extracted_parameters,
            "missing_parameters": self.missing_parameters,
            "complete": self.complete,
            "current_node": self.current_node,
            "date": self.date.isoformat() if isinstance(self.date, datetime) else self.date,
        }

    @classmethod
    def from_dict(cls, state_dict: Dict[str, Any]) -> "State":
        """Create a State from a dictionary coming from storage or older
        schema formats.

        This method tolerates missing keys and multiple shapes for the
        user_message and date fields to remain backward-compatible.
        """
        # Accept either 'user_message' or legacy 'userMessage' keys
        um = state_dict.get("user_message")
        if um is None:
            um = state_dict.get("userMessage")

        user_message: Optional[Union[UserMessage, Dict[str, Any]]] = None
        if isinstance(um, dict):
            # prefer to rehydrate into UserMessage when the helper exists
            try:
                user_message = UserMessage.from_dict(um)
            except Exception:
                # If rehydration fails, keep the raw dict (opaque storage)
                user_message = um
        elif isinstance(um, UserMessage):
            user_message = um
        else:
            user_message = None

        # parse date accepting both ISO strings and datetime objects
        raw_date = state_dict.get("date") or state_dict.get("_date")
        parsed_date: Optional[datetime] = None
        if isinstance(raw_date, datetime):
            parsed_date = raw_date
        elif isinstance(raw_date, str):
            try:
                # datetime.fromisoformat handles most ISO forms
                parsed_date = datetime.fromisoformat(raw_date)
            except Exception:
                parsed_date = None

        return cls(
            thread_id=state_dict.get("thread_id") or state_dict.get("threadId") or "",
            user_message=user_message,
            bot_message=state_dict.get("bot_message")
            or state_dict.get("botMessage")
            or [],
            context=state_dict.get("context") or {},
            intent=state_dict.get("intent") or {},
            parameters=state_dict.get("parameters") or [],
            extracted_parameters=state_dict.get("extracted_parameters")
            or state_dict.get("extractedParameters")
            or {},
            missing_parameters=state_dict.get("missing_parameters")
            or state_dict.get("missingParameters")
            or [],
            complete=state_dict.get("complete", False),
            current_node=state_dict.get("current_node")
            or state_dict.get("currentNode")
            or "",
            date=parsed_date,
        )

    def update(self, user_message: Union[UserMessage, Dict[str, Any]]) -> None:
        """Update state with an incoming user message.

        The incoming user_message can be either a UserMessage instance or a
        dict following the stable serialization format. The state's date is
        refreshed and the incoming context is merged into the existing one.
        """
        # rehydrate dict form if necessary
        if isinstance(user_message, dict):
            try:
                self.user_message = UserMessage.from_dict(user_message)
            except Exception:
                # keep the raw dict if rehydration is not possible
                self.user_message = user_message
        else:
            self.user_message = user_message

        self.date = datetime.now(timezone.utc)

        # merge contexts if available
        incoming_context = None
        try:
            incoming_context = (
                self.user_message.context
                if hasattr(self.user_message, "context")
                else None
            )
        except Exception:
            incoming_context = None

        if isinstance(incoming_context, dict):
            self.context.update(incoming_context)

        if self.complete:
            # Reset conversational artifacts when starting a new turn
            self.bot_message = []
            self.intent = {}
            self.parameters = []
            self.extracted_parameters = {}
            self.missing_parameters = []
            self.complete = False
            self.current_node = ""

    def get_active_intent_id(self) -> Optional[str]:
        """Return the active intent id if available, otherwise None."""
        if self.intent:
            return self.intent.get("id")
        return None