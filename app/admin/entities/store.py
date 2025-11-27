"""Entity store module with validation, soft delete, audit logging, and pagination."""
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from bson import ObjectId

from app.admin.entities.schemas import Entity, EntityCreate, EntityUpdate
from app.database import database

logger = logging.getLogger(__name__)

entity_collection = database.get_collection("entity")
audit_collection = database.get_collection("entity_audit")


async def _ensure_indexes() -> None:
    """Create indexes on commonly queried fields for performance optimization."""
    try:
        await entity_collection.create_index("name", unique=False)
        await entity_collection.create_index("is_deleted")
        await entity_collection.create_index([("name", 1), ("is_deleted", 1)])
        await entity_collection.create_index("created_at")
        await entity_collection.create_index("updated_at")
        logger.debug("Entity collection indexes created successfully")
    except Exception as e:
        logger.error(f"Failed to create indexes: {e}")


async def _log_audit(
    entity_id: str,
    action: str,
    changes: Dict,
    user_id: Optional[str] = None,
) -> None:
    """Log audit trail for entity operations.
    
    Args:
        entity_id: ID of the entity being modified
        action: Type of action (create, update, delete, restore)
        changes: Dictionary of changes made
        user_id: Optional user ID performing the action
    """
    try:
        audit_entry = {
            "entity_id": ObjectId(entity_id) if entity_id else None,
            "action": action,
            "changes": changes,
            "user_id": user_id,
            "timestamp": datetime.utcnow(),
        }
        await audit_collection.insert_one(audit_entry)
        logger.debug(f"Audit logged for entity {entity_id}: {action}")
    except Exception as e:
        logger.error(f"Failed to log audit for entity {entity_id}: {e}")


async def _validate_entity_data(entity_data: dict) -> None:
    """Validate entity data before insert/update.
    
    Args:
        entity_data: Entity data to validate
        
    Raises:
        ValueError: If validation fails
    """
    if not entity_data.get("name"):
        raise ValueError("Entity name is required")
    
    if len(entity_data.get("name", "")) > 255:
        raise ValueError("Entity name must not exceed 255 characters")
    
    entity_values = entity_data.get("entity_values", [])
    if not isinstance(entity_values, list):
        raise ValueError("entity_values must be a list")
    
    for idx, value in enumerate(entity_values):
        if not isinstance(value, dict):
            raise ValueError(f"entity_values[{idx}] must be a dictionary")
        if not value.get("value"):
            raise ValueError(f"entity_values[{idx}].value is required")


async def add_entity(entity_data: dict, user_id: Optional[str] = None) -> Entity:
    """Add a new entity with validation and audit logging.
    
    Args:
        entity_data: Entity data to insert
        user_id: Optional user ID performing the action
        
    Returns:
        Created Entity object
        
    Raises:
        ValueError: If validation fails
    """
    await _validate_entity_data(entity_data)
    
    # Add metadata
    entity_data["is_deleted"] = False
    entity_data["created_at"] = datetime.utcnow()
    entity_data["updated_at"] = datetime.utcnow()
    
    result = await entity_collection.insert_one(entity_data)
    entity_id = str(result.inserted_id)
    
    await _log_audit(entity_id, "create", entity_data, user_id)
    logger.info(f"Entity created: {entity_id}")
    
    return await get_entity(entity_id)


async def get_entity(id: str) -> Entity:
    """Get a single entity by ID (excludes soft-deleted entities).
    
    Args:
        id: Entity ID
        
    Returns:
        Entity object
    """
    entity = await entity_collection.find_one({
        "_id": ObjectId(id),
        "is_deleted": False,
    })
    if not entity:
        raise ValueError(f"Entity not found: {id}")
    return Entity.model_validate(entity)


async def list_entities(
    page: int = 1,
    page_size: int = 50,
    skip: Optional[int] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    name_filter: Optional[str] = None,
) -> Tuple[List[Entity], int]:
    """List entities with pagination, filtering, and sorting (excludes soft-deleted entities).
    
    Args:
        page: Page number (1-indexed)
        page_size: Number of entities per page
        skip: Optional skip value (overrides page calculation)
        sort_by: Field to sort by (name, created_at, updated_at)
        sort_order: Sort order (asc or desc)
        name_filter: Optional name filter for partial matching
        
    Returns:
        Tuple of (entities list, total count)
        
    Raises:
        ValueError: If parameters are invalid
    """
    if page_size <= 0:
        raise ValueError("page_size must be greater than 0")
    if page < 1:
        raise ValueError("page must be greater than or equal to 1")
    
    # Validate sort parameters
    valid_sort_fields = {"name", "created_at", "updated_at"}
    if sort_by not in valid_sort_fields:
        raise ValueError(f"sort_by must be one of: {', '.join(valid_sort_fields)}")
    
    if sort_order not in {"asc", "desc"}:
        raise ValueError("sort_order must be 'asc' or 'desc'")
    
    skip_value = skip if skip is not None else (page - 1) * page_size
    
    query = {"is_deleted": False}
    
    # Apply name filter if provided
    if name_filter:
        query["name"] = {"$regex": name_filter, "$options": "i"}
    
    total_count = await entity_collection.count_documents(query)
    
    # Determine sort direction
    sort_direction = 1 if sort_order == "asc" else -1
    
    entities = await entity_collection.find(query).sort(
        sort_by, sort_direction
    ).skip(skip_value).limit(page_size).to_list()
    
    return [Entity.model_validate(entity) for entity in entities], total_count


async def edit_entity(
    entity_id: str,
    entity_data: dict,
    user_id: Optional[str] = None,
) -> Entity:
    """Update an entity with validation and audit logging.
    
    Args:
        entity_id: Entity ID to update
        entity_data: Updated entity data
        user_id: Optional user ID performing the action
        
    Returns:
        Updated Entity object
        
    Raises:
        ValueError: If validation fails or entity not found
    """
    # Verify entity exists and is not deleted
    existing = await entity_collection.find_one({
        "_id": ObjectId(entity_id),
        "is_deleted": False,
    })
    if not existing:
        raise ValueError(f"Entity not found: {entity_id}")
    
    await _validate_entity_data({**existing, **entity_data})
    
    entity_data["updated_at"] = datetime.utcnow()
    
    await entity_collection.update_one(
        {"_id": ObjectId(entity_id)},
        {"$set": entity_data}
    )
    
    await _log_audit(entity_id, "update", entity_data, user_id)
    logger.info(f"Entity updated: {entity_id}")
    
    return await get_entity(entity_id)


async def delete_entity(entity_id: str, user_id: Optional[str] = None) -> None:
    """Soft delete an entity (marks as deleted instead of removing).
    
    Args:
        entity_id: Entity ID to delete
        user_id: Optional user ID performing the action
        
    Raises:
        ValueError: If entity not found
    """
    existing = await entity_collection.find_one({
        "_id": ObjectId(entity_id),
        "is_deleted": False,
    })
    if not existing:
        raise ValueError(f"Entity not found: {entity_id}")
    
    await entity_collection.update_one(
        {"_id": ObjectId(entity_id)},
        {
            "$set": {
                "is_deleted": True,
                "deleted_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        }
    )
    
    await _log_audit(entity_id, "delete", {"is_deleted": True}, user_id)
    logger.info(f"Entity soft deleted: {entity_id}")


async def restore_entity(entity_id: str, user_id: Optional[str] = None) -> Entity:
    """Restore a soft-deleted entity.
    
    Args:
        entity_id: Entity ID to restore
        user_id: Optional user ID performing the action
        
    Returns:
        Restored Entity object
        
    Raises:
        ValueError: If entity not found or not deleted
    """
    existing = await entity_collection.find_one({"_id": ObjectId(entity_id)})
    if not existing:
        raise ValueError(f"Entity not found: {entity_id}")
    
    if not existing.get("is_deleted"):
        raise ValueError(f"Entity is not deleted: {entity_id}")
    
    await entity_collection.update_one(
        {"_id": ObjectId(entity_id)},
        {
            "$set": {
                "is_deleted": False,
                "updated_at": datetime.utcnow(),
            },
            "$unset": {"deleted_at": ""},
        }
    )
    
    await _log_audit(entity_id, "restore", {"is_deleted": False}, user_id)
    logger.info(f"Entity restored: {entity_id}")
    
    return await get_entity(entity_id)


async def list_synonyms() -> Dict[str, str]:
    """List all synonyms across active entities.
    
    Returns:
        Dictionary mapping synonyms to their values
    """
    synonyms = {}
    
    entities, _ = await list_entities(page_size=1000)
    for entity in entities:
        for value in entity.entity_values:
            for synonym in value.synonyms:
                synonyms[synonym] = value.value
    
    return synonyms


async def bulk_import_entities(
    entities: List[Dict],
    user_id: Optional[str] = None,
) -> List[str]:
    """Bulk import entities with optimized bulk_write and validation.
    
    Args:
        entities: List of entity data to import
        user_id: Optional user ID performing the action
        
    Returns:
        List of created/updated entity IDs
        
    Raises:
        ValueError: If validation fails
    """
    if not entities:
        return []
    
    # Validate all entities first
    for entity in entities:
        await _validate_entity_data(entity)
    
    # Prepare bulk operations
    from pymongo import UpdateOne
    
    operations = []
    created_ids = []
    
    for entity in entities:
        entity["is_deleted"] = False
        entity["updated_at"] = datetime.utcnow()
        
        # Use upsert to create or update
        operation = UpdateOne(
            {"name": entity.get("name")},
            {
                "$set": entity,
                "$setOnInsert": {"created_at": datetime.utcnow()},
            },
            upsert=True,
        )
        operations.append(operation)
    
    if operations:
        result = await entity_collection.bulk_write(operations)
        
        # Log audit for bulk import
        await _log_audit(
            "",
            "bulk_import",
            {
                "count": len(entities),
                "upserted": result.upserted_ids,
                "modified": result.modified_count,
            },
            user_id,
        )
        
        logger.info(
            f"Bulk import completed: {result.upserted_count} created, "
            f"{result.modified_count} updated"
        )
        
        # Fetch created entity IDs
        if result.upserted_ids:
            created_ids = [str(id) for id in result.upserted_ids.values()]
    
    return created_ids


async def get_audit_log(
    entity_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """Retrieve audit log entries.
    
    Args:
        entity_id: Optional entity ID to filter by
        action: Optional action type to filter by
        limit: Maximum number of entries to return
        
    Returns:
        List of audit log entries
    """
    query = {}
    
    if entity_id:
        query["entity_id"] = ObjectId(entity_id)
    
    if action:
        query["action"] = action
    
    entries = await audit_collection.find(query).sort("timestamp", -1).limit(limit).to_list()
    
    return entries