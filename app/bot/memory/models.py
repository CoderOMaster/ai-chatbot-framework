from __future__ import annotations
from typing import Optional, Dict, List, Any, Text
from datetime import datetime, UTC
from app.bot.dialogue_manager.models import UserMessage


class State:
    """Conversation state DTO (v1.0).

    This object captures the evolving dialogue context for a thread.
    Keep serialization stable to avoid persistence incompatibilities.
    """

    VERSION: str = "1.0"

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
        current_node: Optional[Text] = "",
        date: Optional[datetime] = None,
    ):
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
        """Rehydrate State from a dict persisted in storage.

        Note: user_message/bot_message/nlu/date are intentionally omitted
        because persistence layer strips them to minimize storage size.
        """
        return cls(
            thread_id=state_dict["thread_id"],
            context=state_dict.get("context", {}),
            intent=state_dict.get("intent", {}),
            parameters=state_dict.get("parameters", []),
            extracted_parameters=state_dict.get("extracted_parameters", {}),
            missing_parameters=state_dict.get("missing_parameters", []),
            complete=state_dict.get("complete", False),
            current_node=state_dict.get("current_node", ""),
        )

    def update(self, user_message: UserMessage) -> None:
        self.user_message = user_message
        self.date = datetime.now(UTC)
        # Merge context
        if hasattr(user_message, "context") and isinstance(user_message.context, dict):
            self.context.update(user_message.context)

        if self.complete:
            self.bot_message = []
            self.intent = None
            self.parameters = []
            self.extracted_parameters = {}
            self.missing_parameters = []
            self.complete = False
            self.current_node = None

    def get_active_intent_id(self) -> Optional[str]:
        if self.intent:
            return self.intent.get("id")
        return None