"""
Database connection and configuration module.

This module provides MongoDB client initialization, connection pooling,
and database access patterns for the application. It maintains a single
AsyncIOMotorClient per process and exposes get_collection helpers for
dependency injection and easier mocking.
"""

from typing import Annotated, Optional
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from pydantic import PlainSerializer, PlainValidator

# Type annotation for MongoDB ObjectId fields
ObjectIdField = Annotated[
    ObjectId,
    PlainSerializer(lambda x: str(x), return_type=str),
    PlainValidator(lambda x: ObjectId(x)),
]

# Global client and database references - initialized once at startup
_client: Optional[AsyncIOMotorClient] = None
_database: Optional[AsyncIOMotorDatabase] = None


def get_mongo_client(settings) -> AsyncIOMotorClient:
    """
    Create MongoDB AsyncIOMotorClient with connection pooling.
    
    Args:
        settings: Settings instance with MongoDB configuration
        
    Returns:
        AsyncIOMotorClient: Configured MongoDB client
    """
    client = AsyncIOMotorClient(
        settings.MONGODB_HOST,
        maxPoolSize=settings.MONGODB_MAX_POOL_SIZE,
        minPoolSize=settings.MONGODB_MIN_POOL_SIZE,
        socketTimeoutMS=settings.MONGODB_SOCKET_TIMEOUT_MS,
        connectTimeoutMS=settings.MONGODB_CONNECT_TIMEOUT_MS,
    )
    return client


async def init_db(settings) -> None:
    """
    Initialize database connection during application startup.
    
    Creates global client and database references for use throughout
    the application lifecycle. Should be called once at startup.
    
    Args:
        settings: Settings instance with MongoDB configuration
        
    Raises:
        RuntimeError: If database is already initialized
    """
    global _client, _database
    
    if _client is not None:
        raise RuntimeError("Database already initialized. Call close_db() first.")
    
    _client = get_mongo_client(settings)
    _database = _client.get_database(settings.MONGODB_DATABASE)


async def close_db() -> None:
    """
    Close database connection during application shutdown.
    
    Properly closes the MongoDB client connection and clears global references.
    """
    global _client, _database
    if _client:
        _client.close()
    _client = None
    _database = None


def get_db() -> AsyncIOMotorDatabase:
    """
    Get the global database instance for dependency injection.
    
    Returns:
        AsyncIOMotorDatabase: The initialized database instance
        
    Raises:
        RuntimeError: If database has not been initialized
    """
    if _database is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _database


def get_collection(collection_name: str) -> AsyncIOMotorCollection:
    """
    Get a specific collection from the database.
    
    This helper method provides a cleaner interface for accessing collections
    and makes it easier to mock database access in tests.
    
    Args:
        collection_name: Name of the collection to retrieve
        
    Returns:
        AsyncIOMotorCollection: The requested collection
        
    Raises:
        RuntimeError: If database has not been initialized
    """
    db = get_db()
    return db[collection_name]


def get_client() -> AsyncIOMotorClient:
    """
    Get the global MongoDB client instance.
    
    Returns:
        AsyncIOMotorClient: The initialized client instance
        
    Raises:
        RuntimeError: If client has not been initialized
    """
    if _client is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _client


# Backward compatibility: client proxy for legacy code
class _ClientProxy:
    """
    Proxy for backward compatibility with old client import pattern.
    
    Delegates attribute access to the global _client instance.
    """
    
    def __getattr__(self, name: str):
        """
        Proxy attribute access to the global client.
        
        Args:
            name: Attribute name
            
        Returns:
            Attribute from the global client
            
        Raises:
            RuntimeError: If client has not been initialized
        """
        if _client is None:
            raise RuntimeError("Database not initialized. Call init_db() first.")
        return getattr(_client, name)
    
    def close(self) -> None:
        """Close the client connection."""
        if _client:
            _client.close()


# Legacy client proxy for backward compatibility
client = _ClientProxy()