from typing import List, Dict
from bson import ObjectId
from app.admin.intents.schemas import Intent
from app.common.config import Settings
from app.common.database import get_db

_settings = Settings()


async def _collection():
    db = await get_db(_settings)
    return db.get_collection("intent")


async def add_intent(intent_data: dict) -> Intent:
    col = await _collection()
    result = await col.insert_one(intent_data)
    return await get_intent(str(result.inserted_id))


async def get_intent(id: str) -> Intent:
    col = await _collection()
    intent = await col.find_one({"_id": ObjectId(id)})
    return Intent.model_validate(intent)


async def list_intents() -> List[Intent]:
    col = await _collection()
    intents = await col.find().to_list(length=None)
    return [Intent.model_validate(intent) for intent in intents]


async def edit_intent(intent_id: str, intent_data: dict):
    col = await _collection()
    await col.update_one({"_id": ObjectId(intent_id)}, {"$set": intent_data})


async def delete_intent(intent_id: str):
    col = await _collection()
    await col.delete_one({"_id": ObjectId(intent_id)})


async def bulk_import_intents(intents: List[Dict]) -> List[str]:
    col = await _collection()
    created_intents = []
    if intents:
        for intent in intents:
            result = await col.update_one(
                {"name": intent.get("name")}, {"$set": intent}, upsert=True
            )
            if result.upserted_id:
                created_intents.append(str(result.upserted_id))
    return created_intents