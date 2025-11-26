"""MongoDB implementation of MemorySaver for persistent conversation state storage.

This module provides a MongoDB-backed storage implementation for conversation state,
enabling persistence across service restarts and multi-instance deployments. The
implementation supports pagination and retention policies to prevent unbounded
history growth.
"""

from motor.motor_asyncio import AsyncIOMotorClient
from typing import Text, Optional, List
from app.bot.memory.models import State
from app.bot.memory import MemorySaver


class MemorySaverMongo(MemorySaver):
    """MongoDB implementation of MemorySaver for persistent state storage.
    
    Stores conversation state in MongoDB with support for pagination and retention
    policies. This implementation is suitable for production deployments requiring
    persistent state across service restarts and multi-instance configurations.
    
    The AsyncIOMotorClient is injected via constructor to enable dependency injection
    and facilitate testing with mock clients.
    
    Attributes:
        client: AsyncIOMotorClient instance for MongoDB operations.
        db: MongoDB database instance (chatbot).
        collection: MongoDB collection instance (state).
        max_history_per_thread: Maximum number of state records to retain per thread.
    """

    # Default retention policy: keep last 1000 states per thread
    DEFAULT_MAX_HISTORY_PER_THREAD = 1000

    def __init__(
        self,
        client: AsyncIOMotorClient,
        max_history_per_thread: int = DEFAULT_MAX_HISTORY_PER_THREAD,
    ) -> None:
        """Initialize MemorySaverMongo with injected MongoDB client.
        
        Args:
            client: AsyncIOMotorClient instance for MongoDB operations. Must be
                properly configured and connected before use.
            max_history_per_thread: Maximum number of state records to retain per
                conversation thread. Defaults to 1000. Set to 0 to disable retention
                policy (not recommended for production).
                
        Raises:
            TypeError: If client is not an AsyncIOMotorClient instance.
            ValueError: If max_history_per_thread is negative.
        """
        if not isinstance(client, AsyncIOMotorClient):
            raise TypeError(
                f"Expected AsyncIOMotorClient, got {type(client).__name__}"
            )
        if max_history_per_thread < 0:
            raise ValueError("max_history_per_thread must be non-negative")

        self.client = client
        self.db = client.get_database("chatbot")
        self.collection = self.db.get_collection("state")
        self.max_history_per_thread = max_history_per_thread

    async def init_state(self, thread_id: Text) -> State:
        """Initialize a new state for a given thread_id.
        
        Creates a fresh State object for a new conversation thread.
        
        Args:
            thread_id: Unique identifier for the conversation thread.
            
        Returns:
            A new State instance initialized with the given thread_id.
        """
        return State(thread_id=thread_id)

    async def save(self, thread_id: Text, state: State) -> None:
        """Persist state to MongoDB for a given thread_id.
        
        Inserts the state document into the collection and enforces retention
        policy by removing oldest records if the thread exceeds max_history_per_thread.
        
        Args:
            thread_id: Unique identifier for the conversation thread.
            state: The State object to persist.
            
        Raises:
            TypeError: If state is not a State instance.
        """
        if not isinstance(state, State):
            raise TypeError(f"Expected State, got {type(state).__name__}")

        # Insert the state document
        await self.collection.insert_one(state.to_dict())

        # Enforce retention policy if enabled
        if self.max_history_per_thread > 0:
            await self._enforce_retention_policy(thread_id)

    async def get(self, thread_id: Text) -> Optional[State]:
        """Retrieve the latest state for a given thread_id from MongoDB.
        
        Fetches the most recent state document for the specified thread, excluding
        transient fields (nlu, user_message, bot_message) to reduce payload size.
        
        Args:
            thread_id: Unique identifier for the conversation thread.
            
        Returns:
            The latest State object if found, None otherwise.
        """
        result = await self.collection.find_one(
            {"thread_id": thread_id},
            {"_id": 0, "nlu": 0, "date": 0, "user_message": 0, "bot_message": 0},
            sort=[("$natural", -1)],
        )
        if result:
            return State.from_dict(result)
        return None

    async def get_all(
        self, thread_id: Text, limit: int = 100, skip: int = 0
    ) -> List[State]:
        """Retrieve paginated state history for a given thread_id.
        
        Fetches a paginated list of state documents for the specified thread,
        ordered from newest to oldest. Pagination prevents unbounded memory usage
        when retrieving large conversation histories.
        
        Args:
            thread_id: Unique identifier for the conversation thread.
            limit: Maximum number of records to return. Defaults to 100.
                Set to 0 to retrieve all records (use with caution).
            skip: Number of records to skip (for pagination). Defaults to 0.
            
        Returns:
            A list of State objects for the thread (up to limit records),
            ordered from newest to oldest. Empty list if none found.
            
        Raises:
            ValueError: If limit or skip are negative.
        """
        if limit < 0:
            raise ValueError("limit must be non-negative")
        if skip < 0:
            raise ValueError("skip must be non-negative")

        query = self.collection.find(
            {"thread_id": thread_id}, sort=[("$natural", -1)]
        )

        # Apply pagination
        if skip > 0:
            query = query.skip(skip)
        if limit > 0:
            query = query.limit(limit)

        results = await query.to_list(length=None)
        return [State.from_dict(result) for result in results]

    async def _enforce_retention_policy(self, thread_id: Text) -> None:
        """Enforce retention policy by removing oldest records if limit exceeded.
        
        Deletes the oldest state records for a thread if the total count exceeds
        max_history_per_thread. This prevents unbounded growth of the collection.
        
        Args:
            thread_id: Unique identifier for the conversation thread.
        """
        # Count total records for this thread
        count = await self.collection.count_documents({"thread_id": thread_id})

        # If count exceeds limit, remove oldest records
        if count > self.max_history_per_thread:
            excess = count - self.max_history_per_thread
            # Find and delete the oldest excess records
            oldest_records = await self.collection.find(
                {"thread_id": thread_id}, sort=[("$natural", 1)]
            ).to_list(length=excess)

            if oldest_records:
                ids_to_delete = [record["_id"] for record in oldest_records]
                await self.collection.delete_many({"_id": {"$in": ids_to_delete}})