from typing import Dict, List, Protocol

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection

from app.admin.intents.schemas import Intent


class IntentRepository(Protocol):
    """Interface for intent persistence operations."""

    async def add_intent(self, intent_data: dict) -> Intent:
        """Insert a new intent into the underlying store."""

    async def get_intent(self, intent_id: str) -> Intent:
        """Retrieve an intent by its identifier."""

    async def list_intents(self) -> List[Intent]:
        """Return all intents from the underlying store."""

    async def edit_intent(self, intent_id: str, intent_data: dict) -> None:
        """Update an existing intent."""

    async def delete_intent(self, intent_id: str) -> None:
        """Remove an intent from the store."""

    async def bulk_import_intents(self, intents: List[Dict]) -> List[str]:
        """Upsert multiple intents and return identifiers for created entries."""


async def add_intent(collection: AsyncIOMotorCollection, intent_data: dict) -> Intent:
    """Insert a single intent document and return the persisted object."""
    result = await collection.insert_one(intent_data)
    return await get_intent(collection, str(result.inserted_id))


async def get_intent(collection: AsyncIOMotorCollection, intent_id: str) -> Intent:
    """Fetch an intent document by its MongoDB identifier."""
    intent = await collection.find_one({"_id": ObjectId(intent_id)})
    return Intent.model_validate(intent)


async def list_intents(collection: AsyncIOMotorCollection) -> List[Intent]:
    """List all stored intents."""
    intents = await collection.find().to_list(length=None)
    return [Intent.model_validate(intent) for intent in intents]


async def edit_intent(
    collection: AsyncIOMotorCollection, intent_id: str, intent_data: dict
) -> None:
    """Apply updates to an intent document."""
    await collection.update_one(
        {"_id": ObjectId(intent_id)}, {"$set": intent_data}
    )


async def delete_intent(collection: AsyncIOMotorCollection, intent_id: str) -> None:
    """Delete an intent document."""
    await collection.delete_one({"_id": ObjectId(intent_id)})


async def bulk_import_intents(
    collection: AsyncIOMotorCollection, intents: List[Dict]
) -> List[str]:
    """Insert or update multiple intents and return any newly created ids."""
    created_intents: List[str] = []
    if intents:
        for intent in intents:
            result = await collection.update_one(
                {"name": intent.get("name")}, {"$set": intent}, upsert=True
            )
            if result.upserted_id:
                created_intents.append(str(result.upserted_id))
    return created_intents


class MongoIntentRepository(IntentRepository):
    """MongoDB implementation of the intent repository."""

    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._collection = collection

    async def add_intent(self, intent_data: dict) -> Intent:
        """Insert a new intent document."""
        return await add_intent(self._collection, intent_data)

    async def get_intent(self, intent_id: str) -> Intent:
        """Retrieve an intent document by id."""
        return await get_intent(self._collection, intent_id)

    async def list_intents(self) -> List[Intent]:
        """Return all intent documents."""
        return await list_intents(self._collection)

    async def edit_intent(self, intent_id: str, intent_data: dict) -> None:
        """Update an existing intent document."""
        await edit_intent(self._collection, intent_id, intent_data)

    async def delete_intent(self, intent_id: str) -> None:
        """Remove an intent document."""
        await delete_intent(self._collection, intent_id)

    async def bulk_import_intents(self, intents: List[Dict]) -> List[str]:
        """Upsert multiple intents and return created identifiers."""
        return await bulk_import_intents(self._collection, intents)


__all__ = [
    "Intent",
    "IntentRepository",
    "MongoIntentRepository",
    "add_intent",
    "get_intent",
    "list_intents",
    "edit_intent",
    "delete_intent",
    "bulk_import_intents",
]


# End of intent store module