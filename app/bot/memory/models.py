from __future__ import annotations

from datetime import datetime, UTC
from typing import Any, Dict, List, Optional, Text

from app.bot.dialogue_manager.models import UserMessage


class State:
    """Holds the serializable conversation state that memory services persist."""

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
        self.bot_message = bot_message
        self.nlu: Dict[str, Any] = {}
        self.context = context or {}
        self.intent = intent or {}
        self.parameters = parameters or []
        self.extracted_parameters = extracted_parameters or {}
        self.missing_parameters = missing_parameters or []
        self.complete = complete
        self.current_node = current_node
        self.date = date or datetime.now(UTC)

    def to_dict(self) -> Dict[str, Any]:
        """Return a storage-friendly representation of the conversation state."""

        user_message = (
            self.user_message.to_dict() if self.user_message else None
        )
        return {
            "thread_id": self.thread_id,
            "user_message": user_message,
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
        """Rehydrate a State instance from its serialized form, preserving compatibility."""

        user_message_payload = state_dict.get("user_message")
        return_state = cls(
            thread_id=state_dict["thread_id"],
            user_message=cls._deserialize_user_message(user_message_payload),
            bot_message=state_dict.get("bot_message"),
            context=state_dict.get("context"),
            intent=state_dict.get("intent"),
            parameters=state_dict.get("parameters"),
            extracted_parameters=state_dict.get("extracted_parameters"),
            missing_parameters=state_dict.get("missing_parameters"),
            complete=state_dict.get("complete", False),
            current_node=state_dict.get("current_node", ""),
            date=cls._normalize_date(state_dict.get("date")),
        )
        return_state.nlu = state_dict.get("nlu", {})
        return return_state

    @staticmethod
    def _deserialize_user_message(
        payload: Optional[Any]
    ) -> Optional[UserMessage]:
        if isinstance(payload, UserMessage):
            return payload
        if isinstance(payload, dict):
            return UserMessage.from_dict(payload)
        return None

    @staticmethod
    def _normalize_date(value: Optional[Any]) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        return datetime.now(UTC)

    def update(self, user_message: UserMessage) -> None:
        """Refresh the state when a new user message arrives."""

        self.user_message = user_message
        self.date = datetime.now(UTC)
        self.context.update(user_message.context)

        if self.complete:
            self.bot_message = []
            self.intent = None
            self.parameters = []
            self.extracted_parameters = {}
            self.missing_parameters = []
            self.complete = False
            self.current_node = None

    def get_active_intent_id(self) -> Optional[Text]:
        """Return the identifier of the currently tracked intent, if any."""

        if self.intent:
            return self.intent.get("id")
        return None
'}{