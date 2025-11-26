from __future__ import annotations

from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Dict, List, Optional, Text

from app.bot.memory.models import State


__all__ = ["MemorySaver", "MemorySaverInMemory"]


class MemorySaver(ABC):
    """Abstract async interface for storing conversation State objects.

    Implementations of this interface should provide durable and concurrent
    storage for production (e.g. a Mongo/Redis-backed implementation).

    The default init_state implementation returns a fresh State instance and
    is provided as a convenience for implementations that don't need
    special construction logic.

    Note: concrete implementations must be provided via dependency injection
    in application code (do not import store implementations directly inside
    higher-level modules like the dialogue-manager).
    """

    async def init_state(self, thread_id: Text) -> State:
        """Create and return a new State for the provided thread_id.

        This default implementation returns a plain State instance. Override
        if your backend requires custom initialization.
        """
        return State(thread_id=thread_id)

    @abstractmethod
    async def save(self, thread_id: Text, state: State) -> None:
        """Persist the provided state for the given thread_id.

        Implementations should perform any necessary serialization and
        persistence required by their backend.
        """

    @abstractmethod
    async def get(self, thread_id: Text) -> Optional[State]:
        """Return the latest State for thread_id, or None if not found."""

    @abstractmethod
    async def get_all(self, thread_id: Text) -> List[State]:
        """Return all stored State entries for the given thread_id.

        The list should be ordered from oldest to newest.
        """


class MemorySaverInMemory(MemorySaver):
    """A very small in-memory MemorySaver useful for testing.

    WARNING: This implementation is ONLY suitable for single-process tests.
    It is not durable, not shared between processes, and does not provide
    any concurrency guarantees. For production use provide a persistent
    implementation (e.g. MemorySaverMongo) via dependency injection.
    """

    def __init__(self) -> None:
        # thread_id -> list[State]
        self.memory: Dict[Text, List[State]] = OrderedDict()

    async def save(self, thread_id: Text, state: State) -> None:
        """Append a state to the in-memory log for thread_id."""
        if thread_id not in self.memory:
            self.memory[thread_id] = []
        self.memory[thread_id].append(state)

    async def get(self, thread_id: Text) -> Optional[State]:
        """Return the most recent State for thread_id or None if missing."""
        entries = self.memory.get(thread_id)
        if not entries:
            return None
        return entries[-1]

    async def get_all(self, thread_id: Text) -> List[State]:
        """Return all stored states for thread_id (oldest first)."""
        return list(self.memory.get(thread_id, []))