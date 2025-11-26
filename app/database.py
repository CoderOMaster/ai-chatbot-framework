"""MongoDB client helpers and ObjectId field for Pydantic models.

This module exposes lazy initializers and accessor helpers so callers can
inject configuration during initialization (useful for tests, Lambdas and
long-running services). It avoids importing application settings at module
import time; if no configuration is provided, it will lazily load the
project's app config when first needed.
"""
from typing import Annotated, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pydantic import BaseModel, PlainSerializer, PlainValidator

ObjectIdField = Annotated[
    ObjectId,
    PlainSerializer(lambda x: str(x), return_type=str),
    PlainValidator(lambda x: ObjectId(x)),
]


class MongoSettings(BaseModel):
    """Minimal settings required to configure the Mongo client.

    Prefer passing an instance of this class to init_mongo_client so callers
    (applications or tests) can control the database host and name explicitly.
    """

    host: str
    database: str


# Internal module state kept private; use init_mongo_client to configure.
_client: Optional[AsyncIOMotorClient] = None
_database_name: Optional[str] = None


def init_mongo_client(settings: Optional[MongoSettings] = None) -> AsyncIOMotorClient:
    """Initialize (lazily) and return an AsyncIOMotorClient.

    If ``settings`` is not provided the function will import and use the
    project's app config provider at call time. Callers should prefer
    providing MongoSettings to make configuration explicit and testable.
    """
    global _client, _database_name
    if _client is not None:
        return _client

    if settings is None:
        # Import lazily to avoid touching environment/config at module import time.
        from app.config import get_app_config

        cfg = get_app_config()
        settings = MongoSettings(host=cfg.MONGODB_HOST, database=cfg.MONGODB_DATABASE)

    _client = AsyncIOMotorClient(settings.host)
    _database_name = settings.database
    return _client


def get_client() -> AsyncIOMotorClient:
    """Return the initialized AsyncIOMotorClient, initializing it from app
    config if necessary.
    """
    if _client is None:
        return init_mongo_client()
    return _client


def get_database():
    """Return the Motor database instance configured by init_mongo_client.

    Raises RuntimeError if the client hasn't been initialized and the
    underlying app config does not provide a database name.
    """
    client = get_client()
    if _database_name is None:
        # Best-effort: if client can provide a default database use it, otherwise
        # raise a clear error.
        try:
            return client.get_default_database()
        except Exception:
            raise RuntimeError("Mongo database name not configured. Call init_mongo_client first.")
    return client.get_database(_database_name)


def get_collection(name: str) -> AsyncIOMotorCollection:
    """Return a lazily-resolved collection by name.

    Use this helper in application code to avoid importing a raw database
    instance; it makes it easier to swap the persistence implementation in
    the future.
    """
    return get_database()[name]


# Backwards-compatible lazy proxies: some code imports `client` or
# `database` from this module. These proxies forward attribute access to the
# real objects but do not create them until actually used.
class _ClientProxy:
    def __getattr__(self, item):
        return getattr(get_client(), item)

    def __repr__(self):  # pragma: no cover - simple delegation
        return repr(get_client())


class _DatabaseProxy:
    def __getattr__(self, item):
        return getattr(get_database(), item)

    def __repr__(self):  # pragma: no cover - simple delegation
        return repr(get_database())


# Export proxies for compatibility with older code that expects module-level
# `client` and `database` objects. New code should prefer init_mongo_client and
# the get_collection helper to make dependencies explicit.
client = _ClientProxy()
database = _DatabaseProxy()

__all__ = [
    "ObjectIdField",
    "MongoSettings",
    "init_mongo_client",
    "get_client",
    "get_database",
    "get_collection",
    "client",
    "database",
]