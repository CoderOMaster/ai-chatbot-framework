"""
Database connection factory and FastAPI dependency helpers for MongoDB.

This module provides:
- get_mongo_client(settings) -> AsyncIOMotorClient: factory that constructs a Motor client
  using configurable connection pool and timeout settings.
- init_database(settings) / close_database(): lifecycle helpers to initialize and close
  module-level client/database references. These should be called from application
  startup/shutdown lifecycles.
- get_db() -> AsyncIOMotorDatabase: dependency-friendly function that returns the configured
  database instance (singleton client).
- check_db_connection(db, retries=...) -> bool: async health-check helper which attempts
  a `ping` command with an exponential backoff.


Other modules should import get_db as a dependency instead of importing module-level
`client`/`database` singletons where possible. Stores that need top-level collection
access should resolve collections at runtime via get_db() to avoid import-time
configuration ordering issues.
"""
from typing import Optional
import asyncio
import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import PyMongoError
from bson import ObjectId

from app.common.config import get_settings

logger = logging.getLogger(__name__)

# module-level singletons (populated by init_database)
client: Optional[AsyncIOMotorClient] = None
database: Optional[AsyncIOMotorDatabase] = None


class ObjectIdField(str):
    """Pydantic-compatible field type for MongoDB ObjectId values.

    This simple adapter accepts either an ObjectId or a string and normalizes
    to a string representation for JSON/DTO use.
    """

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if v is None:
            return None
        if isinstance(v, ObjectId):
            return str(v)
        return str(v)


# existing helpers
_client_singleton: Optional[AsyncIOMotorClient] = None


def _build_mongo_uri(settings) -> str:
    host = settings.MONGODB_HOST
    if host.startswith("mongodb://") or host.startswith("mongodb+srv://"):
        return host

    username = settings.MONGODB_USERNAME
    password = settings.MONGODB_PASSWORD

    if username and password:
        return f"mongodb://{username}:{password}@{host}"

    return f"mongodb://{host}"


def get_mongo_client(settings=None) -> AsyncIOMotorClient:
    """Return a configured AsyncIOMotorClient singleton.

    The client is created lazily on first use and cached for the process lifetime.
    Connection pooling and timeout parameters are read from Settings so they can be
    controlled via environment variables.
    """
    global _client_singleton
    if _client_singleton is not None:
        return _client_singleton

    if settings is None:
        settings = get_settings()

    uri = _build_mongo_uri(settings)

    client_kwargs = {
        # pymongo options expected by motor
        "maxPoolSize": settings.MONGODB_MAX_POOL_SIZE,
        "connectTimeoutMS": settings.MONGODB_CONNECT_TIMEOUT_MS,
        "serverSelectionTimeoutMS": settings.MONGODB_SERVER_SELECTION_TIMEOUT_MS,
    }

    # remove None values (in case optional settings were left unset)
    client_kwargs = {k: v for k, v in client_kwargs.items() if v is not None}

    logger.debug("Creating AsyncIOMotorClient for %s with %s", uri, client_kwargs)
    _client_singleton = AsyncIOMotorClient(uri, **client_kwargs)
    return _client_singleton


def init_database(settings=None):
    """Initialize module-level client and database references.

    This function is synchronous by design because creating the motor client does
    not perform network I/O until the first operation. Call this early during
    application startup so other modules can reference `client`/`database`.
    """
    global client, database
    if settings is None:
        settings = get_settings()

    client = get_mongo_client(settings)
    database = client.get_database(settings.MONGODB_DATABASE)
    logger.info("Database initialized for %s", settings.MONGODB_DATABASE)


def close_database():
    """Close the underlying MongoDB client connection."""
    global client, database
    if client is not None:
        try:
            client.close()
            logger.info("MongoDB client closed")
        except Exception:
            logger.exception("Error while closing MongoDB client")
    client = None
    database = None


def get_db() -> AsyncIOMotorDatabase:
    """FastAPI-friendly dependency that returns the AsyncIOMotorDatabase instance.

    Usage in routers:
        from app.database import get_db
        db = Depends(get_db)

    This function is intentionally synchronous because creating the motor client is
    cheap (it does not perform I/O until first operation) and FastAPI accepts sync
    dependencies. Returning the database object (not the client) keeps call-sites
    concise.
    """
    settings = get_settings()
    # prefer module-level database set during init_database, fallback to creating one
    global database
    if database is not None:
        return database

    client_local = get_mongo_client(settings)
    return client_local.get_database(settings.MONGODB_DATABASE)


async def check_db_connection(
    db: AsyncIOMotorDatabase, *, retries: Optional[int] = None, backoff_factor: Optional[float] = None
) -> bool:
    """Perform a simple `ping` command against MongoDB with retries and exponential backoff.

    Returns True when the ping succeeds, False otherwise.
    """
    settings = get_settings()
    if retries is None:
        retries = settings.MONGODB_HEALTHCHECK_RETRIES
    if backoff_factor is None:
        backoff_factor = settings.MONGODB_HEALTHCHECK_BACKOFF_FACTOR

    attempt = 0
    while attempt <= max(0, retries):
        try:
            # `ping` is a cheap server command to validate connectivity
            await db.command("ping")
            return True
        except PyMongoError as exc:
            logger.warning("MongoDB ping failed on attempt %s/%s: %s", attempt + 1, retries + 1, exc)
            if attempt == retries:
                break
            # exponential backoff
            sleep_for = backoff_factor * (2 ** attempt)
            await asyncio.sleep(sleep_for)
            attempt += 1
    return False


__all__ = [
    "get_mongo_client",
    "get_db",
    "check_db_connection",
    "init_database",
    "close_database",
    "ObjectIdField",
    "client",
    "database",
]