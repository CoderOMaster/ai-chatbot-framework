from typing import List, Dict

from bson import ObjectId

from app.admin.entities.schemas import Entity
from app.common.config import Settings
from app.common.database import get_db

_settings = Settings()


async def _collection():
    db = await get_db(_settings)
    return db.get_collection("entity")


async def add_entity(entity_data: dict) -> Entity:
    col = await _collection()
    result = await col.insert_one(entity_data)
    return await get_entity(str(result.inserted_id))


async def get_entity(id: str) -> Entity:
    col = await _collection()
    entity = await col.find_one({"_id": ObjectId(id)})
    return Entity.model_validate(entity)


async def list_entities() -> List[Entity]:
    col = await _collection()
    entities = await col.find().to_list(length=None)
    return [Entity.model_validate(entity) for entity in entities]


async def edit_entity(entity_id: str, entity_data: dict):
    col = await _collection()
    await col.update_one({"_id": ObjectId(entity_id)}, {"$set": entity_data})


async def delete_entity(entity_id: str):
    col = await _collection()
    await col.delete_one({"_id": ObjectId(entity_id)})


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
    col = await _collection()
    created_entities = []
    if entities:
        for entity in entities:
            result = await col.update_one(
                {"name": entity.get("name")}, {"$set": entity}, upsert=True
            )
            if result.upserted_id:
                created_entities.append(str(result.upserted_id))
    return created_entities