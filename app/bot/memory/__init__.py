from collections import OrderedDict
from typing import Text, Optional, List, TYPE_CHECKING, Dict, Any
import abc

if TYPE_CHECKING:
    # Imported only for type checking to avoid runtime circular imports
    from app.bot.memory.models import State


class MemorySaver(abc.ABC):
    """Abstract interface for memory backends.

    Implementations should provide async context-management so resources
    (connections, clients) can be acquired and released when used in an
    async with block. The concrete backends must implement save/get/get_all.
    """

    async def init_state(self, thread_id: Text) -> "State":
        """Create and return a fresh State for the provided thread_id.

        State is imported lazily to avoid circular import problems at module
        import time.
        """
        from app.bot.memory.models import State

        return State(thread_id=thread_id)

    @abc.abstractmethod
    async def save(self, thread_id: Text, state: "State") -> None:
        """Persist the provided State for thread_id.

        Implementations decide whether to store State objects, snapshots or
        serialized blobs. Should raise on fatal errors.
        """

    @abc.abstractmethod
    async def get(self, thread_id: Text) -> Optional["State"]:
        """Return the latest State for thread_id or None if not found."""

    @abc.abstractmethod
    async def get_all(self, thread_id: Text) -> List["State"]:
        """Return all stored State entries (history) for thread_id."""

    @abc.abstractmethod
    async def __aenter__(self) -> "MemorySaver":
        """Enter asynchronous context. Open resources if required."""

    @abc.abstractmethod
    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Exit asynchronous context. Ensure resources are cleaned up."""


class MemorySaverInMemory(MemorySaver):
    """In-memory MemorySaver suitable for testing and simple local runs.

    This implementation stores State objects in an OrderedDict of lists and
    implements the async context manager methods as no-ops so it can be used
    with `async with` uniformly alongside IO-backed implementations.
    """

    def __init__(self) -> None:
        self.memory: Dict[Text, List["State"]] = OrderedDict()

    async def __aenter__(self) -> "MemorySaverInMemory":
        # No-op for in-memory backend
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        # Nothing to clean up for in-memory backend
        return None

    async def save(self, thread_id: Text, state: "State") -> None:
        """Append the provided State to the thread's history."""
        if thread_id not in self.memory:
            self.memory[thread_id] = []
        self.memory[thread_id].append(state)

    async def get(self, thread_id: Text) -> Optional["State"]:
        """Return the latest State for the thread or None if absent."""
        if thread_id not in self.memory:
            return None
        entries = self.memory.get(thread_id)
        return entries[-1] if entries else None

    async def get_all(self, thread_id: Text) -> List["State"]:
        """Return the full history of State objects for the thread."""
        if thread_id not in self.memory:
            return []
        return list(self.memory.get(thread_id))