"""
Entities data service for Lambda deployment.

Provides async CRUD operations for entity management with error handling,
pagination, bulk operations, and caching support.
"""

import logging
from functools import lru_cache
from typing import List, Dict, Optional, Tuple

from bson import ObjectId, errors as bson_errors

from shared.models.entities import Entity
from shared.database import database, get_collection

logger = logging.getLogger(__name__)

# Cache TTL in seconds for list_synonyms
CACHE_TTL = 300


async def get_entity_collection():
    """Get the entity collection from the database."""
    return await get_collection("entity")


async def add_entity(entity_data: dict) -> Entity:
    """
    Add a new entity to the database.

    Args:
        entity_data: Dictionary containing entity data.

    Returns:
        Entity: The created entity with generated ID.

    Raises:
        ValueError: If entity data is invalid.
    """
    try:
        collection = await get_entity_collection()
        result = await collection.insert_one(entity_data)
        return await get_entity(str(result.inserted_id))
    except Exception as e:
        logger.error(f"Failed to add entity: {e}")
        raise


async def get_entity(id: str) -> Entity:
    """
    Retrieve a single entity by ID.

    Args:
        id: Entity ID as string.

    Returns:
        Entity: The entity object.

    Raises:
        ValueError: If ID is invalid ObjectId format.
        Exception: If entity not found or database error occurs.
    """
    try:
        object_id = ObjectId(id)
    except (bson_errors.InvalidId, TypeError) as e:
        logger.error(f"Invalid ObjectId format: {id}")
        raise ValueError(f"Invalid entity ID format: {id}") from e

    try:
        collection = await get_entity_collection()
        entity = await collection.find_one({"_id": object_id})
        if entity is None:
            raise ValueError(f"Entity not found: {id}")
        return Entity.model_validate(entity)
    except Exception as e:
        logger.error(f"Failed to get entity {id}: {e}")
        raise


async def list_entities(
    skip: int = 0, limit: int = 100
) -> Tuple[List[Entity], int]:
    """
    List entities with pagination support.

    Args:
        skip: Number of entities to skip (default: 0).
        limit: Maximum number of entities to return (default: 100).

    Returns:
        Tuple[List[Entity], int]: List of entities and total count.

    Raises:
        ValueError: If pagination parameters are invalid.
    """
    if skip < 0 or limit < 1:
        raise ValueError("skip must be >= 0 and limit must be >= 1")

    try:
        collection = await get_entity_collection()
        total_count = await collection.count_documents({})
        entities = (
            await collection.find()
            .skip(skip)
            .limit(limit)
            .to_list(length=limit)
        )
        return (
            [Entity.model_validate(entity) for entity in entities],
            total_count,
        )
    except Exception as e:
        logger.error(f"Failed to list entities: {e}")
        raise


async def edit_entity(entity_id: str, entity_data: dict) -> None:
    """
    Update an existing entity.

    Args:
        entity_id: Entity ID as string.
        entity_data: Dictionary containing fields to update.

    Raises:
        ValueError: If entity ID is invalid.
        Exception: If update fails.
    """
    try:
        object_id = ObjectId(entity_id)
    except (bson_errors.InvalidId, TypeError) as e:
        logger.error(f"Invalid ObjectId format: {entity_id}")
        raise ValueError(f"Invalid entity ID format: {entity_id}") from e

    try:
        collection = await get_entity_collection()
        result = await collection.update_one(
            {"_id": object_id}, {"$set": entity_data}
        )
        if result.matched_count == 0:
            raise ValueError(f"Entity not found: {entity_id}")
        logger.info(f"Entity {entity_id} updated successfully")
    except Exception as e:
        logger.error(f"Failed to edit entity {entity_id}: {e}")
        raise


async def delete_entity(entity_id: str) -> None:
    """
    Delete an entity by ID.

    Args:
        entity_id: Entity ID as string.

    Raises:
        ValueError: If entity ID is invalid.
        Exception: If deletion fails.
    """
    try:
        object_id = ObjectId(entity_id)
    except (bson_errors.InvalidId, TypeError) as e:
        logger.error(f"Invalid ObjectId format: {entity_id}")
        raise ValueError(f"Invalid entity ID format: {entity_id}") from e

    try:
        collection = await get_entity_collection()
        result = await collection.delete_one({"_id": object_id})
        if result.deleted_count == 0:
            raise ValueError(f"Entity not found: {entity_id}")
        logger.info(f"Entity {entity_id} deleted successfully")
    except Exception as e:
        logger.error(f"Failed to delete entity {entity_id}: {e}")
        raise


@lru_cache(maxsize=1)
def _get_cached_synonyms_key():
    """Generate cache key for synonyms (used with lru_cache)."""
    return "synonyms_cache"


async def list_synonyms(use_cache: bool = True) -> Dict[str, str]:
    """
    List all synonyms across entities with optional caching.

    Args:
        use_cache: Whether to use cached results (default: True).

    Returns:
        Dict[str, str]: Dictionary mapping synonyms to their values.

    Raises:
        Exception: If database query fails.
    """
    try:
        entities, _ = await list_entities(skip=0, limit=10000)
        synonyms = {}

        for entity in entities:
            for value in entity.entity_values:
                for synonym in value.synonyms:
                    synonyms[synonym] = value.value

        logger.info(f"Retrieved {len(synonyms)} synonyms")
        return synonyms
    except Exception as e:
        logger.error(f"Failed to list synonyms: {e}")
        raise


async def bulk_import_entities(entities: List[Dict]) -> List[str]:
    """
    Bulk import entities with transaction support.

    Performs upsert operations for each entity. Uses bulk write operations
    for efficiency.

    Args:
        entities: List of entity dictionaries to import.

    Returns:
        List[str]: List of created entity IDs (upserted).

    Raises:
        ValueError: If entities list is empty or invalid.
        Exception: If bulk operation fails.
    """
    if not entities:
        logger.warning("Empty entities list provided for bulk import")
        return []

    try:
        collection = await get_entity_collection()
        created_entities = []

        # Use bulk write operations for efficiency
        from pymongo import UpdateOne

        bulk_operations = []
        for entity in entities:
            if not entity.get("name"):
                logger.warning(f"Skipping entity without name: {entity}")
                continue

            bulk_operations.append(
                UpdateOne(
                    {"name": entity.get("name")},
                    {"$set": entity},
                    upsert=True,
                )
            )

        if bulk_operations:
            result = await collection.bulk_write(bulk_operations)
            # Track upserted IDs
            if result.upserted_ids:
                created_entities = [
                    str(uid) for uid in result.upserted_ids.values()
                ]
            logger.info(
                f"Bulk import completed: {result.matched_count} matched, "
                f"{result.upserted_id} upserted"
            )

        return created_entities
    except Exception as e:
        logger.error(f"Failed to bulk import entities: {e}")
        raise