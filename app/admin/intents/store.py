from typing import Any, Dict, List, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import UpdateOne

from app.admin.intents.schemas import Intent, to_object_id


class InvalidObjectId(ValueError):
    """Raised when a provided id cannot be parsed as a BSON ObjectId.

    This is a lightweight exception (not FastAPI-specific) so callers in different
    contexts (HTTP handlers, background jobs, tests) can decide how to translate
    the error into an appropriate response (e.g. HTTP 400).
    """


def parse_object_id(value: str) -> ObjectId:
    """Parse a string into a bson.ObjectId.

    Args:
        value: hex string representation of an ObjectId

    Returns:
        ObjectId: parsed ObjectId

    Raises:
        InvalidObjectId: if the input is not a valid ObjectId
    """
    try:
        return to_object_id(value)
    except Exception as exc:  # noqa: BLE001 - rewrap third-party exceptions
        raise InvalidObjectId(f"Invalid ObjectId '{value}': {exc}") from exc


def _intent_to_dto(intent_obj: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a raw DB intent document into a plain DTO (no Pydantic models).

    This reduces coupling between storage and higher-level application code.
    The returned DTO always contains an "id" field as a hex string (or None).
    """
    if intent_obj is None:
        return None

    # Validate/normalise using the Pydantic model, but return a plain dict.
    model = Intent.model_validate(intent_obj)
    data = model.model_dump(by_alias=True)

    # Normalise BSON _id into string id
    raw_id = data.pop("_id", None)
    data["id"] = str(raw_id) if raw_id is not None else None
    return data


class IntentRepository:
    """Repository for intent storage operations.

    The repository is deliberately lightweight and requires an AsyncIOMotorCollection
    to be passed in. This enables tests to provide a stubbed collection and avoids
    module-level singletons.
    """

    def __init__(self, collection: AsyncIOMotorCollection):
        self.collection = collection

    @classmethod
    def from_database(cls, db: AsyncIOMotorDatabase) -> "IntentRepository":
        """Create a repository from a Motor/AsyncIOMotorDatabase instance.

        Args:
            db: AsyncIOMotorDatabase

        Returns:
            IntentRepository
        """
        return cls(db.get_collection("intent"))

    async def add_intent(self, intent_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Insert a new intent document and return the created DTO.

        Uses the collection.insert_one and returns the fresh document via get_intent.
        """
        result = await self.collection.insert_one(intent_data)
        return await self.get_intent(str(result.inserted_id))

    async def get_intent(self, id: str) -> Optional[Dict[str, Any]]:
        """Retrieve an intent by id and return a plain DTO.

        Raises InvalidObjectId when the id is syntactically invalid.
        Returns None when no document is found.
        """
        oid = parse_object_id(id)
        intent = await self.collection.find_one({"_id": oid})
        return _intent_to_dto(intent)

    async def list_intents(self) -> List[Dict[str, Any]]:
        """Return all intents as a list of DTOs."""
        intents = await self.collection.find().to_list(length=None)
        return [_intent_to_dto(i) for i in intents]

    async def edit_intent(self, intent_id: str, intent_data: Dict[str, Any]) -> None:
        """Update fields of an existing intent by id.

        Raises InvalidObjectId when the id is syntactically invalid.
        """
        oid = parse_object_id(intent_id)
        await self.collection.update_one({"_id": oid}, {"$set": intent_data})

    async def delete_intent(self, intent_id: str) -> None:
        """Delete an intent by id.

        Raises InvalidObjectId when the id is syntactically invalid.
        """
        oid = parse_object_id(intent_id)
        await self.collection.delete_one({"_id": oid})

    async def bulk_import_intents(self, intents: List[Dict[str, Any]]) -> List[str]:
        """Bulk upsert intents by name using a single bulk_write operation.

        Returns a list of created document ids (as strings) for upserted documents.
        Uses unordered bulk operations to improve throughput and avoid sequential
        round-trips.
        """
        if not intents:
            return []

        ops = []
        for intent in intents:
            name = intent.get("name")
            if not name:
                continue
            ops.append(UpdateOne({"name": name}, {"$set": intent}, upsert=True))

        if not ops:
            return []

        result = await self.collection.bulk_write(ops, ordered=False)

        # result.upserted_ids is a dict mapping index -> ObjectId
        created_ids = []
        upserted = getattr(result, "upserted_ids", None)
        if upserted:
            for _idx, oid in upserted.items():
                created_ids.append(str(oid))

        return created_ids