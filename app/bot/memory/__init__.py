from typing import Text, Optional, List
from app.bot.memory.models import State


class MemorySaver:
    """
    Abstract interface for memory persistence in distributed systems.
    
    Implementations should provide persistent storage backends suitable for
    distributed environments (e.g., database, cache, message queue).
    
    Not recommended for in-memory implementations due to state loss in
    multi-instance deployments.
    """

    async def init_state(self, thread_id: Text) -> State:
        """
        Initialize a new state for a given thread_id.
        
        Args:
            thread_id: Unique identifier for the conversation thread
            
        Returns:
            State: A new State instance with the given thread_id
        """
        return State(thread_id=thread_id)

    async def save(self, thread_id: Text, state: State):
        """
        Persist the state for a given thread_id.
        
        Args:
            thread_id: Unique identifier for the conversation thread
            state: State object to persist
            
        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError("save method not implemented")

    async def get(self, thread_id) -> Optional[State]:
        """
        Retrieve the most recent state for a given thread_id.
        
        Args:
            thread_id: Unique identifier for the conversation thread
            
        Returns:
            Optional[State]: The most recent state or None if not found
            
        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError("get method not implemented")

    async def get_all(self, thread_id) -> List[State]:
        """
        Retrieve all states for a given thread_id.
        
        Args:
            thread_id: Unique identifier for the conversation thread
            
        Returns:
            List[State]: List of all states for the thread, empty list if none found
            
        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError("get_all method not implemented")