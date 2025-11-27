"""Database client module with connection pooling and health checks."""
from typing import Annotated, Optional
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pydantic import PlainSerializer, PlainValidator
import asyncio
import logging

from app.config import app_config

logger = logging.getLogger(__name__)

# ObjectId field type for Pydantic models
ObjectIdField = Annotated[
    ObjectId,
    PlainSerializer(lambda x: str(x), return_type=str),
    PlainValidator(lambda x: ObjectId(x)),
]


class DatabaseClient:
    """Encapsulates MongoDB client with connection pooling and health checks."""

    def __init__(
        self,
        mongodb_host: str,
        mongodb_database: str,
        max_pool_size: int = 50,
        min_pool_size: int = 10,
        max_idle_time_ms: int = 45000,
        retry_attempts: int = 3,
        retry_delay_ms: int = 100,
    ):
        """Initialize DatabaseClient with connection pooling configuration.

        Args:
            mongodb_host: MongoDB connection string
            mongodb_database: Database name
            max_pool_size: Maximum number of connections in the pool
            min_pool_size: Minimum number of connections in the pool
            max_idle_time_ms: Maximum idle time for connections in milliseconds
            retry_attempts: Number of retry attempts for connection failures
            retry_delay_ms: Delay between retry attempts in milliseconds
        """
        self.mongodb_host = mongodb_host
        self.mongodb_database = mongodb_database
        self.max_pool_size = max_pool_size
        self.min_pool_size = min_pool_size
        self.max_idle_time_ms = max_idle_time_ms
        self.retry_attempts = retry_attempts
        self.retry_delay_ms = retry_delay_ms
        self._client: Optional[AsyncIOMotorClient] = None
        self._database: Optional[AsyncIOMotorDatabase] = None

    async def connect(self) -> None:
        """Establish database connection with retry logic."""
        for attempt in range(self.retry_attempts):
            try:
                self._client = AsyncIOMotorClient(
                    self.mongodb_host,
                    maxPoolSize=self.max_pool_size,
                    minPoolSize=self.min_pool_size,
                    maxIdleTimeMS=self.max_idle_time_ms,
                )
                self._database = self._client.get_database(self.mongodb_database)
                logger.info("Database connection established successfully")
                return
            except Exception as e:
                if attempt < self.retry_attempts - 1:
                    delay = self.retry_delay_ms / 1000
                    logger.warning(
                        f"Connection attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Failed to connect to database after {self.retry_attempts} attempts")
                    raise

    async def disconnect(self) -> None:
        """Close database connection."""
        if self._client:
            self._client.close()
            logger.info("Database connection closed")

    async def health_check(self) -> bool:
        """Perform health check on database connection.

        Returns:
            True if database is healthy, False otherwise
        """
        try:
            if not self._database:
                logger.error("Database not initialized")
                return False
            await self._database.command("ping")
            logger.debug("Database health check passed")
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    @property
    def client(self) -> AsyncIOMotorClient:
        """Get the MongoDB client instance.

        Returns:
            AsyncIOMotorClient instance

        Raises:
            RuntimeError: If client is not initialized
        """
        if not self._client:
            raise RuntimeError("Database client not initialized. Call connect() first.")
        return self._client

    @property
    def database(self) -> AsyncIOMotorDatabase:
        """Get the database instance.

        Returns:
            AsyncIOMotorDatabase instance

        Raises:
            RuntimeError: If database is not initialized
        """
        if not self._database:
            raise RuntimeError("Database not initialized. Call connect() first.")
        return self._database


# Initialize default database client instance
_db_client = DatabaseClient(
    mongodb_host=app_config.MONGODB_HOST,
    mongodb_database=app_config.MONGODB_DATABASE,
)


async def get_database_client() -> DatabaseClient:
    """Get the default database client instance.

    Returns:
        DatabaseClient instance
    """
    return _db_client


async def get_database() -> AsyncIOMotorDatabase:
    """Get the default database instance.

    Returns:
        AsyncIOMotorDatabase instance
    """
    return _db_client.database


__all__ = [
    "DatabaseClient",
    "ObjectIdField",
    "get_database_client",
    "get_database",
]