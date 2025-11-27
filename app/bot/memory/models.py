from typing import Optional, Dict, List, Any, Text, Protocol, Mapping
from datetime import datetime, UTC
from dataclasses import dataclass, field
from copy import deepcopy

# Schema version for persisted State blobs - bump this when making incompatible changes
STATE_SCHEMA_VERSION = 1


class UserMessageLike(Protocol):
    """Protocol describing the minimal surface required from a user message value object.

    This deliberately avoids importing the concrete UserMessage class so alternate
    channel payloads or differently-shaped message objects can be used by memory
    providers without requiring a hard dependency on the dialogue manager.
    """

    thread_id: str
    text: str
    channel: str
    context: Mapping[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        ...


@dataclass(frozen=True)
class Snapshot:
    """Immutable snapshot representing a stored historical State.

    Contains the serialized state blob together with a schema_version and
    timestamp so migrations and rollbacks can be implemented deterministically.
    """

    thread_id: Text
    state_blob: Dict[str, Any]
    schema_version: int = field(default=STATE_SCHEMA_VERSION)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "state_blob": deepcopy(self.state_blob),
            "schema_version": self.schema_version,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Snapshot":
        return cls(
            thread_id=data["thread_id"],
            state_blob=deepcopy(data.get("state_blob", {})),
            schema_version=int(data.get("schema_version", STATE_SCHEMA_VERSION)),
            created_at=data.get("created_at", datetime.now(UTC)),
        )


class State:
    """Runtime conversation state used by memory providers.

    This model is mutable during a conversation but provides helpers for
    creating immutable Snapshot objects to persist historical states.
    """

    def __init__(
        self,
        thread_id: Text,
        user_message: Optional[UserMessageLike] = None,
        bot_message: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        intent: Optional[Dict[str, Any]] = None,
        parameters: Optional[List[Dict[str, Any]]] = None,
        extracted_parameters: Optional[Dict[str, Any]] = None,
        missing_parameters: Optional[List[str]] = None,
        complete: bool = False,
        current_node: Text = "",
        date: Optional[datetime] = None,
    ) -> None:
        self.thread_id: Text = thread_id
        self.user_message: Optional[UserMessageLike] = user_message
        self.bot_message: Optional[List[Dict[str, Any]]] = bot_message or []
        self.nlu: Dict[str, Any] = {}
        # Always store a copy of the provided context to avoid accidental shared-mutable state
        self.context: Dict[str, Any] = deepcopy(context) if context is not None else {}
        self.intent: Dict[str, Any] = deepcopy(intent) if intent is not None else {}
        self.parameters: List[Dict[str, Any]] = deepcopy(parameters) if parameters is not None else []
        self.extracted_parameters: Dict[str, Any] = (
            deepcopy(extracted_parameters) if extracted_parameters is not None else {}
        )
        self.missing_parameters: List[str] = list(missing_parameters or [])
        self.complete: bool = complete
        self.current_node: Text = current_node
        self.date: datetime = date or datetime.now(UTC)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the state into a dict suitable for persistence.

        Adds a schema_version key so stored blobs can be migrated in future releases.
        """
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "thread_id": self.thread_id,
            "user_message": self.user_message.to_dict() if self.user_message is not None else None,
            "bot_message": deepcopy(self.bot_message),
            "nlu": deepcopy(self.nlu),
            "context": deepcopy(self.context),
            "intent": deepcopy(self.intent),
            "parameters": deepcopy(self.parameters),
            "extracted_parameters": deepcopy(self.extracted_parameters),
            "missing_parameters": list(self.missing_parameters),
            "complete": self.complete,
            "current_node": self.current_node,
            "date": self.date,
        }

    @classmethod
    def from_dict(cls, state_dict: Dict[str, Any]) -> "State":
        """Recreate a State from a previously persisted dict.

        This method is tolerant of missing keys (for backwards compatibility) and
        will prefer the schema_version when present (currently used only for
        bookkeeping). It does not attempt to reconstruct a concrete user_message
        instance — user_message will be left as None and consumers may rehydrate
        it if necessary.
        """
        # Read schema version but currently no migration logic is applied here
        _ = int(state_dict.get("schema_version", STATE_SCHEMA_VERSION))

        return cls(
            thread_id=state_dict.get("thread_id", ""),
            user_message=None,
            bot_message=deepcopy(state_dict.get("bot_message") or []),
            context=deepcopy(state_dict.get("context") or {}),
            intent=deepcopy(state_dict.get("intent") or {}),
            parameters=deepcopy(state_dict.get("parameters") or []),
            extracted_parameters=deepcopy(state_dict.get("extracted_parameters") or {}),
            missing_parameters=list(state_dict.get("missing_parameters") or []),
            complete=bool(state_dict.get("complete", False)),
            current_node=state_dict.get("current_node", ""),
            date=state_dict.get("date", None),
        )

    def snapshot(self) -> Snapshot:
        """Return an immutable Snapshot representing the current state.

        Useful for appending to a changelog/history while keeping the runtime
        State mutable for ongoing conversation handling.
        """
        return Snapshot(thread_id=self.thread_id, state_blob=self.to_dict())

    def update(self, user_message: UserMessageLike) -> None:
        """Update the state with a new incoming user message.

        The incoming message's context is copied (deep copy) before being merged
        to ensure there is no shared-mutable state between the message payload
        and the stored conversation context.
        """
        self.user_message = user_message
        self.date = datetime.now(UTC)

        # Merge contexts defensively using deep copies to avoid shared references
        incoming_context = deepcopy(dict(user_message.context)) if user_message.context is not None else {}
        merged = deepcopy(self.context)
        merged.update(incoming_context)
        self.context = merged

        if self.complete:
            # Reset conversation progress while keeping types stable
            self.bot_message = []
            self.intent = {}
            self.parameters = []
            self.extracted_parameters = {}
            self.missing_parameters = []
            self.complete = False
            self.current_node = ""

    def get_active_intent_id(self) -> Optional[Text]:
        """Return the active intent id if present, else None."""
        if self.intent:
            return self.intent.get("id")
        return None