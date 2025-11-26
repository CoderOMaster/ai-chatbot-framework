from typing import Any, Dict, List, Protocol
from bson import ObjectId

from app.admin.intents.schemas import Intent


class IntentRepository(Protocol):
    """Protocol describing the intent persistence interface.

    Implementations must provide async methods to add, retrieve, list,
    update, delete and bulk-import intents. This allows application code to
    depend on the abstract repository instead of a concrete database client.
    """

    async def add_intent(self, intent_data: Dict[str, Any]) -> Intent:  # type: ignore[name-defined]
        ...

    async def get_intent(self, id: str) -> Intent:  # type: ignore[name-defined]
        ...

    async def list_intents(self) -> List[Intent]:
        ...

    async def edit_intent(self, intent_id: str, intent_data: Dict[str, Any]) -> None:
        ...

    async def delete_intent(self, intent_id: str) -> None:
        ...

    async def bulk_import_intents(self, intents: List[Dict[str, Any]]) -> List[str]:
        ...


class MongoIntentRepository:
    """MongoDB implementation of IntentRepository.

    This class expects an async collection-like object (for example
    motor.motor_asyncio.AsyncIOMotorCollection) to be injected so the same
    implementation can be reused across services and tests without relying on a
    global client.
    """

    def __init__(self, collection: Any):
        """Create a repository bound to the provided collection.

        Args:
            collection: An async collection supporting insert_one, find_one,
                find(...).to_list, update_one and delete_one.
        """
        self.collection = collection

    async def add_intent(self, intent_data: Dict[str, Any]) -> Intent:
        result = await self.collection.insert_one(intent_data)
        return await self.get_intent(str(result.inserted_id))

    async def get_intent(self, id: str) -> Intent:
        intent = await self.collection.find_one({"_id": ObjectId(id)})
        return Intent.model_validate(intent)

    async def list_intents(self) -> List[Intent]:
        intents = await self.collection.find().to_list(None)
        return [Intent.model_validate(intent) for intent in intents]

    async def edit_intent(self, intent_id: str, intent_data: Dict[str, Any]) -> None:
        await self.collection.update_one(
            {"_id": ObjectId(intent_id)}, {"$set": intent_data}
        )

    async def delete_intent(self, intent_id: str) -> None:
        await self.collection.delete_one({"_id": ObjectId(intent_id)})

    async def bulk_import_intents(self, intents: List[Dict[str, Any]]) -> List[str]:
        created_intents: List[str] = []
        if intents:
            for intent in intents:
                result = await self.collection.update_one(
                    {"name": intent.get("name")}, {"$set": intent}, upsert=True
                )
                # motor returns upserted_id when a new document was created
                if getattr(result, "upserted_id", None):
                    created_intents.append(str(result.upserted_id))
        return created_intents