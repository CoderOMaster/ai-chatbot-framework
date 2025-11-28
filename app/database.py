"""Expose MongoDB helpers that can be injected into services."""

from typing import Callable, TypeAlias

from core.settings import AppConfig
from core.types import ObjectIdField
from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
)

__all__ = [
    "ObjectIdField",
    "CollectionGetter",
    "create_mongo_collection_getter",
    "create_collection_getter_from_config",
]

CollectionGetter: TypeAlias = Callable[[str], AsyncIOMotorCollection]


def create_mongo_collection_getter(host: str, database_name: str) -> CollectionGetter:
    """Produce a helper that lazily instantiates a Mongo client and provides collections."""

    client: AsyncIOMotorClient | None = None
    database: AsyncIOMotorDatabase | None = None

    def _ensure_client() -> AsyncIOMotorClient:
        nonlocal client
        if client is None:
            client = AsyncIOMotorClient(host)
        return client

    def _ensure_database() -> AsyncIOMotorDatabase:
        nonlocal database
        if database is None:
            database = _ensure_client().get_database(database_name)
        return database

    def get_collection(collection_name: str) -> AsyncIOMotorCollection:
        """Return the named collection from the cached database."""
        return _ensure_database()[collection_name]

    return get_collection


def create_collection_getter_from_config(config: AppConfig) -> CollectionGetter:
    """Build a collection helper using the provided AppConfig instance."""

    return create_mongo_collection_getter(
        host=config.MONGODB_HOST,
        database_name=config.MONGODB_DATABASE,
    )