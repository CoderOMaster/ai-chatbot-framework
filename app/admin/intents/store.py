"""
Async CRUD and bulk import operations for intents.

This module provides database operations for intent management used by:
- Admin CRUD routes
- Training pipeline
- Dialogue manager initialization

Supports pagination and filtering to efficiently handle large tenant intent collections.
"""

from typing import List, Dict, Optional, Any
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection
from app.admin.intents.schemas import Intent
from app.database import get_collection


async def _get_intent_collection() -> AsyncIOMotorCollection:
    """
    Get the intent collection from the database.
    
    Returns:
        AsyncIOMotorCollection: The intent collection
    """
    return get_collection("intent")


async def add_intent(intent_data: dict) -> Intent:
    """
    Create a new intent in the database.
    
    Args:
        intent_data: Dictionary containing intent fields
        
    Returns:
        Intent: The created intent with generated ID
    """
    collection = await _get_intent_collection()
    result = await collection.insert_one(intent_data)
    return await get_intent(str(result.inserted_id))


async def get_intent(id: str) -> Intent:
    """
    Retrieve a single intent by ID.
    
    Args:
        id: The intent ID as string
        
    Returns:
        Intent: The intent model
        
    Raises:
        ValueError: If intent not found
    """
    collection = await _get_intent_collection()
    intent = await collection.find_one({"_id": ObjectId(id)})
    if not intent:
        raise ValueError(f"Intent with id {id} not found")
    return Intent.model_validate(intent)


async def list_intents(
    skip: int = 0,
    limit: int = 100,
    filter_query: Optional[Dict[str, Any]] = None,
    sort_by: Optional[str] = None,
    sort_order: int = 1
) -> tuple[List[Intent], int]:
    """
    List intents with pagination and filtering support.
    
    Retrieves intents in paginated batches to avoid loading all intents
    into memory for large tenant collections.
    
    Args:
        skip: Number of intents to skip (default: 0)
        limit: Maximum number of intents to return (default: 100, max: 1000)
        filter_query: Optional MongoDB filter query dict (e.g., {"userDefined": True})
        sort_by: Optional field name to sort by (default: "_id")
        sort_order: Sort order: 1 for ascending, -1 for descending (default: 1)
        
    Returns:
        Tuple of (list of Intent models, total count matching filter)
        
    Raises:
        ValueError: If limit exceeds maximum allowed value
    """
    if limit > 1000:
        raise ValueError("Limit cannot exceed 1000")
    
    collection = await _get_intent_collection()
    query = filter_query or {}
    sort_field = sort_by or "_id"
    
    # Get total count matching the filter
    total_count = await collection.count_documents(query)
    
    # Fetch paginated results
    cursor = collection.find(query).skip(skip).limit(limit).sort(sort_field, sort_order)
    intents = await cursor.to_list(length=limit)
    
    return [Intent.model_validate(intent) for intent in intents], total_count


async def get_intents_by_filter(
    filter_query: Dict[str, Any],
    skip: int = 0,
    limit: int = 100
) -> tuple[List[Intent], int]:
    """
    Retrieve intents matching a specific filter with pagination.
    
    Convenience method for common filtering patterns.
    
    Args:
        filter_query: MongoDB filter query dict
        skip: Number of intents to skip
        limit: Maximum number of intents to return
        
    Returns:
        Tuple of (list of Intent models, total count)
    """
    return await list_intents(skip=skip, limit=limit, filter_query=filter_query)


async def get_intents_by_name(
    name: str,
    skip: int = 0,
    limit: int = 100
) -> tuple[List[Intent], int]:
    """
    Retrieve intents by name pattern with pagination.
    
    Args:
        name: Intent name to search for (supports partial matching)
        skip: Number of intents to skip
        limit: Maximum number of intents to return
        
    Returns:
        Tuple of (list of Intent models, total count)
    """
    filter_query = {"name": {"$regex": name, "$options": "i"}}
    return await list_intents(skip=skip, limit=limit, filter_query=filter_query)


async def get_user_defined_intents(
    skip: int = 0,
    limit: int = 100
) -> tuple[List[Intent], int]:
    """
    Retrieve only user-defined intents with pagination.
    
    Args:
        skip: Number of intents to skip
        limit: Maximum number of intents to return
        
    Returns:
        Tuple of (list of Intent models, total count)
    """
    filter_query = {"userDefined": True}
    return await list_intents(skip=skip, limit=limit, filter_query=filter_query)


async def edit_intent(intent_id: str, intent_data: dict) -> None:
    """
    Update an existing intent.
    
    Args:
        intent_id: The intent ID as string
        intent_data: Dictionary of fields to update
        
    Raises:
        ValueError: If intent not found
    """
    collection = await _get_intent_collection()
    result = await collection.update_one(
        {"_id": ObjectId(intent_id)}, 
        {"$set": intent_data}
    )
    if result.matched_count == 0:
        raise ValueError(f"Intent with id {intent_id} not found")


async def delete_intent(intent_id: str) -> None:
    """
    Delete an intent by ID.
    
    Args:
        intent_id: The intent ID as string
        
    Raises:
        ValueError: If intent not found
    """
    collection = await _get_intent_collection()
    result = await collection.delete_one({"_id": ObjectId(intent_id)})
    if result.deleted_count == 0:
        raise ValueError(f"Intent with id {intent_id} not found")


async def bulk_import_intents(intents: List[Dict]) -> List[str]:
    """
    Bulk import or upsert intents by name.
    
    Creates new intents or updates existing ones based on name matching.
    Used by training pipeline and admin bulk operations.
    
    Args:
        intents: List of intent dictionaries to import
        
    Returns:
        List of IDs for newly created intents (upserted_id values)
    """
    collection = await _get_intent_collection()
    created_intents = []
    
    if intents:
        for intent in intents:
            result = await collection.update_one(
                {"name": intent.get("name")}, 
                {"$set": intent}, 
                upsert=True
            )
            if result.upserted_id:
                created_intents.append(str(result.upserted_id))
    
    return created_intents


async def count_intents(filter_query: Optional[Dict[str, Any]] = None) -> int:
    """
    Count intents matching optional filter.
    
    Useful for pagination calculations and statistics.
    
    Args:
        filter_query: Optional MongoDB filter query dict
        
    Returns:
        Count of intents matching the filter
    """
    collection = await _get_intent_collection()
    query = filter_query or {}
    return await collection.count_documents(query)