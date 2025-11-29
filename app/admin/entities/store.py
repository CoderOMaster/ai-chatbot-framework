from typing import Dict, List, Protocol

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection

from app.admin.entities.schemas import Entity


class EntityRepository(Protocol):
    """Interface for entity persistence operations."""

    async def add_entity(self, entity_data: dict) -> Entity:
        """Insert a new entity document into the underlying store."""

    async def get_entity(self, entity_id: str) -> Entity:
        """Retrieve an entity document by its identifier."""

    async def list_entities(self) -> List[Entity]:
        """Return all entity documents from the store."""

    async def edit_entity(self, entity_id: str, entity_data: dict) -> None:
        """Update an existing entity with new data."""

    async def delete_entity(self, entity_id: str) -> None:
        """Remove an entity document from the store."""

    async def list_synonyms(self) -> Dict[str, str]:
        """Expose a dictionary mapping synonyms to canonical values."""

    async def bulk_import_entities(self, entities: List[Dict]) -> List[str]:
        """Upsert a batch of entities and return identifiers created in the process."""


async def add_entity(collection: AsyncIOMotorCollection, entity_data: dict) -> Entity:
    """Insert a single entity document and return the persisted object."""

    result = await collection.insert_one(entity_data)
    return await get_entity(collection, str(result.inserted_id))


async def get_entity(collection: AsyncIOMotorCollection, entity_id: str) -> Entity:
    """Fetch an entity document by its MongoDB identifier."""

    entity = await collection.find_one({"_id": ObjectId(entity_id)})
    return Entity.model_validate(entity)


async def list_entities(collection: AsyncIOMotorCollection) -> List[Entity]:
    """List all stored entity objects."""

    entities = await collection.find().to_list(length=None)
    return [Entity.model_validate(entity) for entity in entities]


async def edit_entity(
    collection: AsyncIOMotorCollection, entity_id: str, entity_data: dict
) -> None:
    """Apply updates to an existing entity document."""

    await collection.update_one(
        {"_id": ObjectId(entity_id)}, {"$set": entity_data}
    )


async def delete_entity(collection: AsyncIOMotorCollection, entity_id: str) -> None:
    """Remove an entity document by its identifier."""

    await collection.delete_one({"_id": ObjectId(entity_id)})


async def list_synonyms(collection: AsyncIOMotorCollection) -> Dict[str, str]:
    """Return all synonyms mapped to their canonical entity values."""

    synonyms: Dict[str, str] = {}
    entities = await list_entities(collection)
    for entity in entities:
        for value in entity.entity_values:
            for synonym in value.synonyms:
                synonyms[synonym] = value.value
    return synonyms


async def bulk_import_entities(
    collection: AsyncIOMotorCollection, entities: List[Dict]
) -> List[str]:
    """Upsert multiple entities and trim any documents not present in the import."""

    created_entities: List[str] = []
    if not entities:
        await collection.delete_many({})
        return created_entities

    canonical_names: set[str] = set()
    for entity in entities:
        name = entity.get("name")
        if not name:
            continue
        canonical_names.add(name)
        result = await collection.update_one(
            {"name": name}, {"$set": entity}, upsert=True
        )
        if result.upserted_id:
            created_entities.append(str(result.upserted_id))

    if canonical_names:
        await collection.delete_many({"name": {"$nin": list(canonical_names)}})
    else:
        await collection.delete_many({})

    return created_entities


class MongoEntityRepository(EntityRepository):
    """MongoDB implementation of the entity repository."""

    def __init__(self, collection: AsyncIOMotorCollection) -> None:
        self._collection = collection

    async def add_entity(self, entity_data: dict) -> Entity:
        """Insert a new entity document into MongoDB."""

        return await add_entity(self._collection, entity_data)

    async def get_entity(self, entity_id: str) -> Entity:
        """Retrieve an entity document by id."""

        return await get_entity(self._collection, entity_id)

    async def list_entities(self) -> List[Entity]:
        """Return every stored entity document."""

        return await list_entities(self._collection)

    async def edit_entity(self, entity_id: str, entity_data: dict) -> None:
        """Update an existing entity document."""

        await edit_entity(self._collection, entity_id, entity_data)

    async def delete_entity(self, entity_id: str) -> None:
        """Remove an entity document from MongoDB."""

        await delete_entity(self._collection, entity_id)

    async def list_synonyms(self) -> Dict[str, str]:
        """Return the synonym map built from stored entities."""

        return await list_synonyms(self._collection)

    async def bulk_import_entities(self, entities: List[Dict]) -> List[str]:
        """Upsert and trim entity documents based on the provided batch."""

        return await bulk_import_entities(self._collection, entities)


__all__ = [
    "Entity",
    "EntityRepository",
    "MongoEntityRepository",
    "add_entity",
    "get_entity",
    "list_entities",
    "edit_entity",
    "delete_entity",
    "list_synonyms",
    "bulk_import_entities",
]


# End of entity store module