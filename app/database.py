"""
Database connectivity module for MongoDB.

Provides factory functions for creating MongoDB clients with connection pooling,
health checks, and retry logic. Supports both microservices and Lambda deployments.
"""

import asyncio
import logging
from typing import Annotated, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pydantic import PlainSerializer, PlainValidator

from shared.config import app_config

logger = logging.getLogger(__name__)

# Shared ObjectId field type for Pydantic models
ObjectIdField = Annotated[
    ObjectId,
    PlainSerializer(lambda x: str(x), return_type=str),
    PlainValidator(lambda x: ObjectId(x)),
]


def create_mongodb_client(
    host: Optional[str] = None,
    max_pool_size: int = 50,
    min_pool_size: int = 10,
    max_idle_time_ms: int = 45000,
    retry_writes: bool = True,
    retry_reads: bool = True,
) -> AsyncIOMotorClient:
    """
    Create a MongoDB AsyncIO client with connection pooling and retry logic.

    Args:
        host: MongoDB connection string. Defaults to app_config.MONGODB_HOST.
        max_pool_size: Maximum number of connections in the pool (default: 50).
        min_pool_size: Minimum number of connections in the pool (default: 10).
        max_idle_time_ms: Maximum idle time for connections in milliseconds (default: 45000).
        retry_writes: Enable automatic retry of write operations (default: True).
        retry_reads: Enable automatic retry of read operations (default: True).

    Returns:
        AsyncIOMotorClient: Configured MongoDB client with connection pooling.
    """
    connection_string = host or app_config.MONGODB_HOST

    client = AsyncIOMotorClient(
        connection_string,
        maxPoolSize=max_pool_size,
        minPoolSize=min_pool_size,
        maxIdleTimeMS=max_idle_time_ms,
        retryWrites=retry_writes,
        retryReads=retry_reads,
        serverSelectionTimeoutMS=5000,
    )

    logger.info(
        f"MongoDB client created with pool size {min_pool_size}-{max_pool_size}"
    )
    return client


async def get_database(
    client: Optional[AsyncIOMotorClient] = None,
    database_name: Optional[str] = None,
) -> AsyncIOMotorDatabase:
    """
    Get a MongoDB database instance.

    Args:
        client: MongoDB client. If None, creates a new one.
        database_name: Database name. Defaults to app_config.MONGODB_DATABASE.

    Returns:
        AsyncIOMotorDatabase: MongoDB database instance.
    """
    if client is None:
        client = create_mongodb_client()

    db_name = database_name or app_config.MONGODB_DATABASE
    return client.get_database(db_name)


async def health_check(
    client: Optional[AsyncIOMotorClient] = None,
    timeout_seconds: int = 5,
) -> bool:
    """
    Perform a health check on the MongoDB connection.

    Args:
        client: MongoDB client to check. If None, creates a new one.
        timeout_seconds: Timeout for the health check in seconds (default: 5).

    Returns:
        bool: True if connection is healthy, False otherwise.
    """
    if client is None:
        client = create_mongodb_client()

    try:
        await asyncio.wait_for(
            client.admin.command("ping"),
            timeout=timeout_seconds,
        )
        logger.info("MongoDB health check passed")
        return True
    except asyncio.TimeoutError:
        logger.error("MongoDB health check timed out")
        return False
    except Exception as e:
        logger.error(f"MongoDB health check failed: {e}")
        return False


async def close_client(client: AsyncIOMotorClient) -> None:
    """
    Close a MongoDB client connection.

    Args:
        client: MongoDB client to close.
    """
    client.close()
    logger.info("MongoDB client closed")


# Default client and database instances for backwards compatibility
# Services should prefer dependency injection over these globals
client = create_mongodb_client()
database = asyncio.run(get_database(client))