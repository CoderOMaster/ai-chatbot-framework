import threading
from collections import OrderedDict
from typing import Text, Optional, List
from datetime import datetime, timedelta, UTC
from shared.models.memory import State


class MemorySaver:
    """
    MemorySaver is an abstract class that defines the interface for a memory saver.
    """

    async def init_state(self, thread_id: Text) -> State:
        """
        Initialize a new state for a given thread_id
        """
        return State(thread_id=thread_id)

    async def save(self, thread_id: Text, state: State):
        """
        append the state to the memory for a given thread_id
        """
        raise NotImplementedError("save method not implemented")

    async def get(self, thread_id) -> Optional[State]:
        raise NotImplementedError("get method not implemented")

    async def get_all(self, thread_id) -> List[State]:
        raise NotImplementedError("get_all method not implemented")


class MemorySaverInMemory(MemorySaver):
    """
    In-memory implementation of MemorySaver with thread-safety and TTL support.
    
    This implementation is intended for testing and development purposes.
    It stores conversation states in memory with optional TTL-based eviction.
    
    Attributes:
        memory: OrderedDict storing states per thread_id
        ttl_seconds: Time-to-live for entries in seconds (None for no expiration)
        lock: Threading lock for thread-safe access
    """
    
    def __init__(self, ttl_seconds: Optional[int] = None):
        """
        Initialize MemorySaverInMemory.
        
        Args:
            ttl_seconds: Time-to-live for entries in seconds. If None, entries never expire.
        """
        self.memory: OrderedDict = OrderedDict()
        self.ttl_seconds = ttl_seconds
        self.lock = threading.Lock()

    def _cleanup_expired(self, thread_id: Text) -> None:
        """
        Remove expired entries for a given thread_id.
        
        Args:
            thread_id: Thread identifier to clean up
        """
        if self.ttl_seconds is None or thread_id not in self.memory:
            return
        
        now = datetime.now(UTC)
        self.memory[thread_id] = [
            state for state in self.memory[thread_id]
            if (now - state.date) < timedelta(seconds=self.ttl_seconds)
        ]
        
        if not self.memory[thread_id]:
            del self.memory[thread_id]

    async def save(self, thread_id: Text, state: State) -> None:
        """
        Save state for a given thread_id with thread-safety.
        
        Args:
            thread_id: Thread identifier
            state: State object to save
        """
        with self.lock:
            if thread_id not in self.memory:
                self.memory[thread_id] = []
            self.memory[thread_id].append(state)

    async def get(self, thread_id: Text) -> Optional[State]:
        """
        Get the most recent state for a given thread_id.
        
        Args:
            thread_id: Thread identifier
            
        Returns:
            Most recent State object or None if not found
        """
        with self.lock:
            self._cleanup_expired(thread_id)
            if thread_id not in self.memory or not self.memory[thread_id]:
                return None
            return self.memory[thread_id][-1]

    async def get_all(self, thread_id: Text) -> List[State]:
        """
        Get all states for a given thread_id.
        
        Args:
            thread_id: Thread identifier
            
        Returns:
            List of State objects for the thread
        """
        with self.lock:
            self._cleanup_expired(thread_id)
            if thread_id not in self.memory:
                return []
            return self.memory[thread_id]