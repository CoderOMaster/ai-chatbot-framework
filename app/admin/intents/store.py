"""
Intents data service for CRUD operations and bulk imports.

Provides async functions for managing conversational intents with error handling,
pagination support, and optimized bulk operations for Lambda deployments.
"""

import logging
from typing import List, Dict, Tuple, Optional
from bson import ObjectId, errors as bson_errors
from shared.models.intents import Intent
from shared.database import database, get_collection

logger = logging.getLogger(__name__)

intent_collection = database.get_collection("intent")


class ObjectIdError(Exception):
    """Raised when ObjectId conversion fails."""
    pass


async def add_intent(intent_data: dict) -> Intent:
    """
    Add a new intent to the database.
    
    Args:
        intent_data: Dictionary containing intent data
        
    Returns:
        Intent: The created intent object
        
    Raises:
        Exception: If database operation fails
    """
    result = await intent_collection.insert_one(intent_data)
    return await get_intent(str(result.inserted_id))


async def get_intent(id: str) -> Intent:
    """
    Retrieve a single intent by ID.
    
    Args:
        id: String representation of the intent ObjectId
        
    Returns:
        Intent: The intent object
        
    Raises:
        ObjectIdError: If ID is not a valid ObjectId
        ValueError: If intent is not found
    """
    try:
        object_id = ObjectId(id)
    except (bson_errors.InvalidId, TypeError) as e:
        logger.error(f"Invalid ObjectId format: {id}")
        raise ObjectIdError(f"Invalid ObjectId format: {id}") from e
    
    intent = await intent_collection.find_one({"_id": object_id})
    if not intent:
        raise ValueError(f"Intent with id {id} not found")
    return Intent.model_validate(intent)


async def list_intents(
    skip: int = 0,
    limit: int = 100,
) -> Tuple[List[Intent], int]:
    """
    List intents with pagination support.
    
    Args:
        skip: Number of intents to skip (default: 0)
        limit: Maximum number of intents to return (default: 100)
        
    Returns:
        Tuple containing:
            - List of Intent objects
            - Total count of intents in database
    """
    total_count = await intent_collection.count_documents({})
    intents = await intent_collection.find().skip(skip).limit(limit).to_list(None)
    return [Intent.model_validate(intent) for intent in intents], total_count


async def edit_intent(intent_id: str, intent_data: dict) -> None:
    """
    Update an existing intent.
    
    Args:
        intent_id: String representation of the intent ObjectId
        intent_data: Dictionary containing fields to update
        
    Raises:
        ObjectIdError: If intent_id is not a valid ObjectId
    """
    try:
        object_id = ObjectId(intent_id)
    except (bson_errors.InvalidId, TypeError) as e:
        logger.error(f"Invalid ObjectId format: {intent_id}")
        raise ObjectIdError(f"Invalid ObjectId format: {intent_id}") from e
    
    await intent_collection.update_one(
        {"_id": object_id}, {"$set": intent_data}
    )


async def delete_intent(intent_id: str) -> None:
    """
    Delete an intent by ID.
    
    Args:
        intent_id: String representation of the intent ObjectId
        
    Raises:
        ObjectIdError: If intent_id is not a valid ObjectId
    """
    try:
        object_id = ObjectId(intent_id)
    except (bson_errors.InvalidId, TypeError) as e:
        logger.error(f"Invalid ObjectId format: {intent_id}")
        raise ObjectIdError(f"Invalid ObjectId format: {intent_id}") from e
    
    await intent_collection.delete_one({"_id": object_id})


async def bulk_import_intents(intents: List[Dict]) -> List[str]:
    """
    Bulk import intents using optimized bulk_write operations.
    
    Performs upsert operations on all intents in a single batch write,
    significantly faster than sequential updates for large imports.
    
    Args:
        intents: List of intent dictionaries to import
        
    Returns:
        List of ObjectIds (as strings) for newly created intents
    """
    if not intents:
        return []
    
    from pymongo import UpdateOne
    
    operations = []
    for intent in intents:
        operations.append(
            UpdateOne(
                {"name": intent.get("name")},
                {"$set": intent},
                upsert=True
            )
        )
    
    try:
        result = await intent_collection.bulk_write(operations)
        # Extract upserted IDs from the bulk write result
        created_intents = [str(uid) for uid in result.upserted_ids.values()]
        logger.info(f"Bulk imported {len(created_intents)} new intents")
        return created_intents
    except Exception as e:
        logger.error(f"Bulk import failed: {e}")
        raise