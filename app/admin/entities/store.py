from typing import List, Dict, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection

from app.admin.entities.schemas import Entity
from app.database import database


class EntityRepository:
    """Repository for CRUD operations on entity documents.

    This repository is storage-agnostic: pass an AsyncIOMotorCollection (or any
    collection-like object with the same async API) to the constructor so
    callers can inject a test double or a sharded collection at runtime.
    """

    def __init__(self, collection: AsyncIOMotorCollection):
        self.collection = collection

    async def add_entity(self, entity_data: dict) -> Entity:
        """Insert a new entity document and return the created Entity model.

        Note: callers should validate uniqueness if required; this method
        performs a simple insert.
        """
        result = await self.collection.insert_one(entity_data)
        return await self.get_entity(str(result.inserted_id))

    async def get_entity(self, id: str) -> Entity:
        """Return an Entity by its string ObjectId.

        Raises the underlying validation/error if the document is not found or
        cannot be converted to the Entity schema.
        """
        entity = await self.collection.find_one({"_id": ObjectId(id)})
        return Entity.model_validate(entity)

    async def list_entities(self) -> List[Entity]:
        """List all entities stored in the collection.

        Uses an async cursor to avoid relying on Motor-specific to_list() arity.
        """
        cursor = self.collection.find()
        entities: List[Entity] = []
        async for doc in cursor:
            entities.append(Entity.model_validate(doc))
        return entities

    async def edit_entity(self, entity_id: str, entity_data: dict) -> None:
        """Update an entity document by its ObjectId string.

        Only the fields provided in entity_data are set on the document.
        """
        await self.collection.update_one({"_id": ObjectId(entity_id)}, {"$set": entity_data})

    async def delete_entity(self, entity_id: str) -> None:
        """Delete an entity document by its ObjectId string."""
        await self.collection.delete_one({"_id": ObjectId(entity_id)})

    async def list_synonyms(self) -> Dict[str, str]:
        """Return a mapping from synonym -> canonical value for all entities.

        This is useful for building NLU synonym maps where each synonym should
        point to its canonical entity value.
        """
        synonyms: Dict[str, str] = {}
        entities = await self.list_entities()
        for entity in entities:
            for value in entity.entity_values:
                for synonym in value.synonyms:
                    synonyms[synonym] = value.value
        return synonyms

    async def bulk_import_entities(self, entities: List[Dict]) -> List[str]:
        """Idempotently import entities by upserting on the entity 'name'.

        For each provided entity dict, upsert based on the 'name' field. After
        processing the provided list, any documents in the collection whose
        names are not present in the import payload will be removed. Returns a
        list of newly created entity IDs (as strings).
        """
        created_entities: List[str] = []
        if not entities:
            return created_entities

        names = [e.get("name") for e in entities if e.get("name")]

        for entity in entities:
            result = await self.collection.update_one(
                {"name": entity.get("name")}, {"$set": entity}, upsert=True
            )
            if getattr(result, "upserted_id", None):
                created_entities.append(str(result.upserted_id))

        # Trim entities that were not present in the import payload.
        if names:
            await self.collection.delete_many({"name": {"$nin": names}})

        return created_entities


def get_default_repository() -> EntityRepository:
    """Return a repository backed by the default 'entity' collection.

    This helper keeps backwards compatibility for callers that do not inject a
    collection. Prefer constructing EntityRepository explicitly in new code.
    """
    return EntityRepository(database.get_collection("entity"))


# Backwards-compatible module-level functions that use the default repository.
# Prefer injecting EntityRepository instances in application code.

_default_repo = None


def _ensure_default_repo() -> EntityRepository:
    global _default_repo
    if _default_repo is None:
        _default_repo = get_default_repository()
    return _default_repo


async def add_entity(entity_data: dict) -> Entity:
    return await _ensure_default_repo().add_entity(entity_data)


async def get_entity(id: str) -> Entity:
    return await _ensure_default_repo().get_entity(id)


async def list_entities() -> List[Entity]:
    return await _ensure_default_repo().list_entities()


async def edit_entity(entity_id: str, entity_data: dict) -> None:
    await _ensure_default_repo().edit_entity(entity_id, entity_data)


async def delete_entity(entity_id: str) -> None:
    await _ensure_default_repo().delete_entity(entity_id)


async def list_synonyms() -> Dict[str, str]:
    return await _ensure_default_repo().list_synonyms()


async def bulk_import_entities(entities: List[Dict]) -> List[str]:
    return await _ensure_default_repo().bulk_import_entities(entities)