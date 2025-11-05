from typing import List, Dict

from bson import ObjectId

from app.admin.entities.schemas import Entity
from app.database import get_db


async def _get_entity_collection():
    db = get_db()
    return db.get_collection("entity")


async def add_entity(entity_data: dict) -> Entity:
    collection = await _get_entity_collection()
    result = await collection.insert_one(entity_data)
    return await get_entity(str(result.inserted_id))


async def get_entity(id: str) -> Entity:
    collection = await _get_entity_collection()
    entity = await collection.find_one({"_id": ObjectId(id)})
    return Entity.model_validate(entity)


async def list_entities() -> List[Entity]:
    collection = await _get_entity_collection()
    entities = await collection.find().to_list()
    return [Entity.model_validate(entity) for entity in entities]


async def edit_entity(entity_id: str, entity_data: dict):
    collection = await _get_entity_collection()
    await collection.update_one({"_id": ObjectId(entity_id)}, {"$set": entity_data})


async def delete_entity(entity_id: str):
    collection = await _get_entity_collection()
    await collection.delete_one({"_id": ObjectId(entity_id)})


async def list_synonyms():
    """list all synonyms across the entities"""
    synonyms = {}

    entities = await list_entities()
    for entity in entities:
        for value in entity.entity_values:
            for synonym in value.synonyms:
                synonyms[synonym] = value.value
    return synonyms


async def bulk_import_entities(entities: List[Dict]) -> List[str]:
    collection = await _get_entity_collection()
    created_entities = []
    if entities:
        for entity in entities:
            result = await collection.update_one(
                {"name": entity.get("name")}, {"$set": entity}, upsert=True
            )
            if result.upserted_id:
                created_entities.append(str(result.upserted_id))
    return created_entities