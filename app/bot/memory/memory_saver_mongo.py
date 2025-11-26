from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from typing import Text, Optional, List, Dict, Any
from datetime import datetime, UTC, timedelta
import asyncio
from shared.models.memory import State
from shared.memory import MemorySaver


class MemorySaverMongo(MemorySaver):
    """
    MongoDB-based implementation of MemorySaver with connection pooling,
    retry logic, and caching support.
    
    This implementation provides persistent storage of conversation states
    in MongoDB with automatic TTL-based cleanup and optional caching of
    recent states for improved performance.
    
    Attributes:
        client: AsyncIOMotorClient for MongoDB connection
        db: MongoDB database instance
        collection: MongoDB collection for state storage
        max_retries: Maximum number of retry attempts for failed operations
        retry_delay: Delay in seconds between retry attempts
        cache_ttl_seconds: TTL for in-memory cache of recent states
        state_cache: In-memory cache for recent states
    """

    def __init__(
        self,
        client: AsyncIOMotorClient,
        max_retries: int = 3,
        retry_delay: float = 0.5,
        cache_ttl_seconds: Optional[int] = 300,
    ):
        """
        Initialize MemorySaverMongo.
        
        Args:
            client: AsyncIOMotorClient for MongoDB connection
            max_retries: Maximum number of retry attempts for failed operations
            retry_delay: Delay in seconds between retry attempts
            cache_ttl_seconds: TTL for in-memory cache of recent states (None to disable)
        """
        self.client = client
        self.db = client.get_database("chatbot")
        self.collection: AsyncIOMotorCollection = self.db.get_collection("state")
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.cache_ttl_seconds = cache_ttl_seconds
        self.state_cache: Dict[Text, tuple[State, datetime]] = {}

    async def init_indexes(self) -> None:
        """
        Initialize MongoDB indexes for optimal query performance.
        
        Creates:
        - Index on thread_id for fast lookups
        - TTL index on date field for automatic state cleanup
        """
        try:
            # Index on thread_id for fast queries
            await self.collection.create_index("thread_id")
            
            # TTL index for automatic cleanup (30 days)
            await self.collection.create_index(
                "date",
                expireAfterSeconds=30 * 24 * 60 * 60,
            )
        except Exception as e:
            # Log but don't fail if indexes already exist
            pass

    async def _retry_operation(
        self,
        operation,
        *args,
        **kwargs,
    ) -> Any:
        """
        Execute an async operation with exponential backoff retry logic.
        
        Args:
            operation: Async callable to execute
            *args: Positional arguments for operation
            **kwargs: Keyword arguments for operation
            
        Returns:
            Result of the operation
            
        Raises:
            Exception: If all retry attempts fail
        """
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                return await operation(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))
        
        raise last_exception

    def _invalidate_cache(self, thread_id: Text) -> None:
        """
        Invalidate cache entry for a given thread_id.
        
        Args:
            thread_id: Thread identifier
        """
        if thread_id in self.state_cache:
            del self.state_cache[thread_id]

    def _get_cached_state(self, thread_id: Text) -> Optional[State]:
        """
        Retrieve state from cache if valid.
        
        Args:
            thread_id: Thread identifier
            
        Returns:
            Cached State if valid and not expired, None otherwise
        """
        if self.cache_ttl_seconds is None or thread_id not in self.state_cache:
            return None
        
        state, cached_at = self.state_cache[thread_id]
        if (datetime.now(UTC) - cached_at) < timedelta(seconds=self.cache_ttl_seconds):
            return state
        
        # Cache expired, remove it
        del self.state_cache[thread_id]
        return None

    def _set_cache(self, thread_id: Text, state: State) -> None:
        """
        Store state in cache.
        
        Args:
            thread_id: Thread identifier
            state: State to cache
        """
        if self.cache_ttl_seconds is not None:
            self.state_cache[thread_id] = (state, datetime.now(UTC))

    async def save(self, thread_id: Text, state: State) -> None:
        """
        Save state to MongoDB with retry logic.
        
        Args:
            thread_id: Thread identifier
            state: State object to save
        """
        async def _save_operation():
            state_dict = state.to_dict()
            state_dict["thread_id"] = thread_id
            await self.collection.insert_one(state_dict)
        
        await self._retry_operation(_save_operation)
        self._invalidate_cache(thread_id)

    async def get(self, thread_id: Text) -> Optional[State]:
        """
        Get the most recent state for a given thread_id with caching.
        
        Attempts to retrieve from cache first, then falls back to MongoDB
        with retry logic.
        
        Args:
            thread_id: Thread identifier
            
        Returns:
            Most recent State object or None if not found
        """
        # Check cache first
        cached_state = self._get_cached_state(thread_id)
        if cached_state is not None:
            return cached_state

        async def _get_operation():
            result = await self.collection.find_one(
                {"thread_id": thread_id},
                {
                    "_id": 0,
                    "nlu": 0,
                    "date": 0,
                    "user_message": 0,
                    "bot_message": 0,
                },
                sort=[("$natural", -1)],
            )
            if result:
                return State.from_dict(result)
            return None

        state = await self._retry_operation(_get_operation)
        if state:
            self._set_cache(thread_id, state)
        return state

    async def get_all(self, thread_id: Text) -> List[State]:
        """
        Get all states for a given thread_id with retry logic.
        
        Args:
            thread_id: Thread identifier
            
        Returns:
            List of State objects for the thread
        """
        async def _get_all_operation():
            cursor = self.collection.find(
                {"thread_id": thread_id},
                sort=[("$natural", -1)],
            )
            results = await cursor.to_list(None)
            return [State.from_dict(result) for result in results]

        return await self._retry_operation(_get_all_operation)