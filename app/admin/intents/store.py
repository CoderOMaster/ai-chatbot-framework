from typing import List, Dict
from bson import ObjectId
from app.admin.intents.schemas import Intent
from app.database import get_db


async def _get_intent_collection():
    db = get_db()
    return db.get_collection("intent")


async def add_intent(intent_data: dict) -> Intent:
    collection = await _get_intent_collection()
    result = await collection.insert_one(intent_data)
    return await get_intent(str(result.inserted_id))


async def get_intent(id: str) -> Intent:
    collection = await _get_intent_collection()
    intent = await collection.find_one({"_id": ObjectId(id)})
    return Intent.model_validate(intent)


async def list_intents() -> List[Intent]:
    collection = await _get_intent_collection()
    intents = await collection.find().to_list()
    return [Intent.model_validate(intent) for intent in intents]


async def edit_intent(intent_id: str, intent_data: dict):
    collection = await _get_intent_collection()
    await collection.update_one({"_id": ObjectId(intent_id)}, {"$set": intent_data})


async def delete_intent(intent_id: str):
    collection = await _get_intent_collection()
    await collection.delete_one({"_id": ObjectId(intent_id)})


async def bulk_import_intents(intents: List[Dict]) -> List[str]:
    collection = await _get_intent_collection()
    created_intents = []
    if intents:
        for intent in intents:
            result = await collection.update_one(
                {"name": intent.get("name")}, {"$set": intent}, upsert=True
            )
            if result.upserted_id:
                created_intents.append(str(result.upserted_id))
    return created_intents