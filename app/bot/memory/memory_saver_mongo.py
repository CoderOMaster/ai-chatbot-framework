import zlib
import json
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Text, Optional, List, Dict, Any
from datetime import datetime, timedelta, UTC
from pydantic import BaseSettings, Field
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError
from app.bot.memory.models import State
from app.bot.memory import MemorySaver


logger = logging.getLogger(__name__)


class MongoSettings(BaseSettings):
    """Configuration for MongoDB memory saver.
    
    Attributes:
        database_name: MongoDB database name
        collection_name: MongoDB collection name for states
        ttl_days: Time-to-live for old states in days (0 = no TTL)
        compression_threshold: Minimum state size in bytes to trigger compression
        max_retries: Maximum number of retry attempts for failed operations
        retry_delay_ms: Delay between retries in milliseconds
    """
    database_name: str = Field(default="chatbot", description="MongoDB database name")
    collection_name: str = Field(default="state", description="MongoDB collection name")
    ttl_days: int = Field(default=30, description="TTL for old states in days")
    compression_threshold: int = Field(default=1024, description="Compression threshold in bytes")
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    retry_delay_ms: int = Field(default=100, description="Retry delay in milliseconds")

    class Config:
        env_prefix = "MONGO_"


class MemorySaverMongo(MemorySaver):
    """MongoDB-backed memory saver with error handling, TTL, compression, and retry logic.
    
    Features:
        - Configurable database and collection names
        - Automatic TTL index for state expiration
        - State compression for large histories
        - Retry logic with exponential backoff
        - Comprehensive error handling and logging
    """

    def __init__(
        self,
        client: AsyncIOMotorClient,
        settings: Optional[MongoSettings] = None,
    ):
        """Initialize MongoDB memory saver.
        
        Args:
            client: AsyncIOMotorClient instance for MongoDB connection
            settings: MongoSettings configuration object (uses defaults if None)
            
        Raises:
            ValueError: If client is None
        """
        if client is None:
            raise ValueError("MongoDB client cannot be None")
        
        self.client = client
        self.settings = settings or MongoSettings()
        self.db = client.get_database(self.settings.database_name)
        self.collection = self.db.get_collection(self.settings.collection_name)
        self._initialized = False

    async def _ensure_indexes(self) -> None:
        """Create necessary indexes for optimal query performance and TTL.
        
        Raises:
            PyMongoError: If index creation fails
        """
        if self._initialized:
            return
        
        try:
            # Index for thread_id queries
            await self.collection.create_index("thread_id")
            
            # TTL index if configured
            if self.settings.ttl_days > 0:
                ttl_seconds = self.settings.ttl_days * 24 * 60 * 60
                await self.collection.create_index(
                    "date",
                    expireAfterSeconds=ttl_seconds,
                )
                logger.info(
                    f"Created TTL index with {self.settings.ttl_days} days expiration"
                )
            
            # Compound index for efficient sorting
            await self.collection.create_index(
                [("thread_id", 1), ("date", -1)]
            )
            
            self._initialized = True
            logger.debug("MongoDB indexes initialized successfully")
        except PyMongoError as e:
            logger.error(f"Failed to create indexes: {str(e)}")
            raise

    async def _retry_operation(
        self,
        operation_name: str,
        operation_func,
        *args,
        **kwargs,
    ) -> Any:
        """Execute operation with retry logic and exponential backoff.
        
        Args:
            operation_name: Name of the operation for logging
            operation_func: Async function to execute
            *args: Positional arguments for operation_func
            **kwargs: Keyword arguments for operation_func
            
        Returns:
            Result of operation_func
            
        Raises:
            PyMongoError: If all retry attempts fail
        """
        last_error = None
        
        for attempt in range(self.settings.max_retries):
            try:
                return await operation_func(*args, **kwargs)
            except (PyMongoError, ServerSelectionTimeoutError) as e:
                last_error = e
                if attempt < self.settings.max_retries - 1:
                    delay = (self.settings.retry_delay_ms * (2 ** attempt)) / 1000
                    logger.warning(
                        f"{operation_name} attempt {attempt + 1} failed: {str(e)}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    await self._async_sleep(delay)
                else:
                    logger.error(
                        f"{operation_name} failed after {self.settings.max_retries} attempts"
                    )
        
        raise last_error

    @staticmethod
    async def _async_sleep(seconds: float) -> None:
        """Non-blocking sleep for async context.
        
        Args:
            seconds: Duration to sleep
        """
        import asyncio
        await asyncio.sleep(seconds)

    def _compress_state(self, state_dict: Dict) -> Dict:
        """Compress state data if it exceeds threshold.
        
        Args:
            state_dict: State dictionary to potentially compress
            
        Returns:
            Dictionary with compressed data if applicable
        """
        state_json = json.dumps(state_dict)
        state_size = len(state_json.encode('utf-8'))
        
        if state_size > self.settings.compression_threshold:
            compressed = zlib.compress(state_json.encode('utf-8'))
            return {
                **state_dict,
                "_compressed": True,
                "_data": compressed.hex(),
            }
        
        return state_dict

    def _decompress_state(self, state_dict: Dict) -> Dict:
        """Decompress state data if it was compressed.
        
        Args:
            state_dict: State dictionary potentially containing compressed data
            
        Returns:
            Decompressed state dictionary
            
        Raises:
            ValueError: If decompression fails
        """
        if state_dict.get("_compressed"):
            try:
                compressed_data = bytes.fromhex(state_dict["_data"])
                decompressed = zlib.decompress(compressed_data)
                return json.loads(decompressed.decode('utf-8'))
            except (ValueError, zlib.error) as e:
                logger.error(f"Failed to decompress state: {str(e)}")
                raise ValueError(f"State decompression failed: {str(e)}") from e
        
        return state_dict

    async def save(self, thread_id: Text, state: State) -> None:
        """Save state to MongoDB with error handling.
        
        Args:
            thread_id: Conversation thread identifier
            state: State object to save
            
        Raises:
            ValueError: If thread_id or state is invalid
            PyMongoError: If database operation fails after retries
        """
        if not thread_id:
            raise ValueError("thread_id cannot be empty")
        if not isinstance(state, State):
            raise ValueError(f"state must be State instance, got {type(state)}")
        
        try:
            await self._ensure_indexes()
            
            state_dict = state.to_dict()
            state_dict = self._compress_state(state_dict)
            
            async def insert_operation():
                return await self.collection.insert_one(state_dict)
            
            result = await self._retry_operation(
                f"save state for thread {thread_id}",
                insert_operation,
            )
            logger.debug(f"State saved for thread {thread_id}: {result.inserted_id}")
        except Exception as e:
            logger.error(f"Failed to save state for thread {thread_id}: {str(e)}")
            raise

    async def get(self, thread_id: Text) -> Optional[State]:
        """Retrieve the most recent state for a thread.
        
        Args:
            thread_id: Conversation thread identifier
            
        Returns:
            Most recent State object or None if not found
            
        Raises:
            ValueError: If thread_id is invalid
            PyMongoError: If database operation fails after retries
        """
        if not thread_id:
            raise ValueError("thread_id cannot be empty")
        
        try:
            await self._ensure_indexes()
            
            async def find_operation():
                return await self.collection.find_one(
                    {"thread_id": thread_id},
                    {"_id": 0, "nlu": 0, "user_message": 0, "bot_message": 0},
                    sort=[("date", -1)],
                )
            
            result = await self._retry_operation(
                f"get state for thread {thread_id}",
                find_operation,
            )
            
            if result:
                result = self._decompress_state(result)
                return State.from_dict(result)
            
            logger.debug(f"No state found for thread {thread_id}")
            return None
        except Exception as e:
            logger.error(f"Failed to get state for thread {thread_id}: {str(e)}")
            raise

    async def get_all(self, thread_id: Text) -> List[State]:
        """Retrieve all states for a thread, sorted by date descending.
        
        Args:
            thread_id: Conversation thread identifier
            
        Returns:
            List of State objects for the thread (empty list if none found)
            
        Raises:
            ValueError: If thread_id is invalid
            PyMongoError: If database operation fails after retries
        """
        if not thread_id:
            raise ValueError("thread_id cannot be empty")
        
        try:
            await self._ensure_indexes()
            
            async def find_all_operation():
                cursor = self.collection.find(
                    {"thread_id": thread_id},
                    sort=[("date", -1)],
                )
                return await cursor.to_list(length=None)
            
            results = await self._retry_operation(
                f"get all states for thread {thread_id}",
                find_all_operation,
            )
            
            states = []
            for result in results:
                try:
                    result = self._decompress_state(result)
                    states.append(State.from_dict(result))
                except Exception as e:
                    logger.warning(
                        f"Failed to deserialize state for thread {thread_id}: {str(e)}"
                    )
                    continue
            
            logger.debug(f"Retrieved {len(states)} states for thread {thread_id}")
            return states
        except Exception as e:
            logger.error(f"Failed to get all states for thread {thread_id}: {str(e)}")
            raise