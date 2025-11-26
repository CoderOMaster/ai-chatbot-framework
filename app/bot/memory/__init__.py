"""Memory management interface and implementations for dialogue state persistence.

This module defines the MemorySaver interface and provides in-memory implementation
for storing and retrieving conversation state. Implementations can be registered
via dependency injection to allow services to swap storage backends without code changes.
"""

from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Text, Optional, List
from app.bot.memory.models import State


class MemorySaver(ABC):
    """Abstract base class defining the interface for memory persistence.
    
    MemorySaver defines the contract for storing and retrieving conversation state
    across different storage backends (in-memory, MongoDB, etc.). Implementations
    should be registered via dependency injection to enable runtime backend swapping.
    
    This interface supports thread-based conversation tracking where each thread_id
    represents a unique conversation session.
    """

    @abstractmethod
    async def init_state(self, thread_id: Text) -> State:
        """Initialize a new state for a given thread_id.
        
        Creates a fresh State object for a new conversation thread. This is typically
        called when starting a new conversation session.
        
        Args:
            thread_id: Unique identifier for the conversation thread.
            
        Returns:
            A new State instance initialized with the given thread_id.
        """
        return State(thread_id=thread_id)

    @abstractmethod
    async def save(self, thread_id: Text, state: State) -> None:
        """Persist state to memory for a given thread_id.
        
        Appends or updates the state in the storage backend. Implementations should
        handle thread-safe operations and ensure state consistency.
        
        Args:
            thread_id: Unique identifier for the conversation thread.
            state: The State object to persist.
            
        Raises:
            NotImplementedError: If the implementation does not support this operation.
        """
        raise NotImplementedError("save method not implemented")

    @abstractmethod
    async def get(self, thread_id: Text) -> Optional[State]:
        """Retrieve the latest state for a given thread_id.
        
        Fetches the most recent state from the storage backend for the specified thread.
        
        Args:
            thread_id: Unique identifier for the conversation thread.
            
        Returns:
            The latest State object if found, None otherwise.
            
        Raises:
            NotImplementedError: If the implementation does not support this operation.
        """
        raise NotImplementedError("get method not implemented")

    @abstractmethod
    async def get_all(self, thread_id: Text) -> List[State]:
        """Retrieve all states for a given thread_id.
        
        Fetches the complete history of states for the specified thread, ordered
        chronologically from oldest to newest.
        
        Args:
            thread_id: Unique identifier for the conversation thread.
            
        Returns:
            A list of State objects for the thread, empty list if none found.
            
        Raises:
            NotImplementedError: If the implementation does not support this operation.
        """
        raise NotImplementedError("get_all method not implemented")


class MemorySaverInMemory(MemorySaver):
    """In-memory implementation of MemorySaver for development and testing.
    
    Stores conversation state in memory using an OrderedDict. This implementation
    is suitable for development, testing, and single-instance deployments where
    persistence across service restarts is not required.
    
    Thread Safety:
        This implementation is not thread-safe. For multi-threaded environments,
        consider using a thread-safe backend like MongoDB.
    """

    def __init__(self) -> None:
        """Initialize the in-memory storage.
        
        Creates an empty OrderedDict to store conversation states indexed by thread_id.
        """
        self.memory: OrderedDict[Text, List[State]] = OrderedDict()

    async def save(self, thread_id: Text, state: State) -> None:
        """Persist state to in-memory storage.
        
        Appends the state to the list of states for the given thread_id.
        If the thread_id does not exist, creates a new list.
        
        Args:
            thread_id: Unique identifier for the conversation thread.
            state: The State object to persist.
        """
        if thread_id not in self.memory:
            self.memory[thread_id] = []
        self.memory[thread_id].append(state)

    async def get(self, thread_id: Text) -> Optional[State]:
        """Retrieve the latest state from in-memory storage.
        
        Returns the most recent state for the given thread_id.
        
        Args:
            thread_id: Unique identifier for the conversation thread.
            
        Returns:
            The latest State object if found, None otherwise.
        """
        if thread_id not in self.memory:
            return None
        states = self.memory.get(thread_id)
        return states[-1] if states else None

    async def get_all(self, thread_id: Text) -> List[State]:
        """Retrieve all states from in-memory storage.
        
        Returns the complete history of states for the given thread_id.
        
        Args:
            thread_id: Unique identifier for the conversation thread.
            
        Returns:
            A list of State objects for the thread, empty list if none found.
        """
        if thread_id not in self.memory:
            return []
        return self.memory.get(thread_id, [])


__all__ = ["MemorySaver", "MemorySaverInMemory"]