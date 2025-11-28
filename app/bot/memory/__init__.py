"""Memory persistence abstractions used by the dialogue manager and memory services."""

from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import List, Optional, Text

from app.bot.memory.models import State


class MemorySaver(ABC):
    """Defines the async interface for memory persistence backends.

    Concrete implementations (e.g., MemorySaverMongo) should be injected
    into the dialogue manager via configuration rather than imported directly
    to keep the dialogue manager agnostic of the underlying storage.
    """

    async def init_state(self, thread_id: Text) -> State:
        """Return a fresh conversation state for the provided thread."""
        return State(thread_id=thread_id)

    @abstractmethod
    async def save(self, thread_id: Text, state: State) -> None:
        """Persist the current conversation state for the given thread."""

    @abstractmethod
    async def get(self, thread_id: Text) -> Optional[State]:
        """Return the most recent state for the provided thread."""

    @abstractmethod
    async def get_all(self, thread_id: Text) -> List[State]:
        """Return the full state history for the provided thread."""


class MemorySaverInMemory(MemorySaver):
    """In-memory implementation suitable for single-process testing only; do not use in production."""

    def __init__(self) -> None:
        self.memory: OrderedDict[Text, List[State]] = OrderedDict()

    async def save(self, thread_id: Text, state: State) -> None:
        if thread_id not in self.memory:
            self.memory[thread_id] = []
        self.memory[thread_id].append(state)

    async def get(self, thread_id: Text) -> Optional[State]:
        if thread_id not in self.memory:
            return None
        return self.memory[thread_id][-1]

    async def get_all(self, thread_id: Text) -> List[State]:
        return list(self.memory.get(thread_id, []))