"""
Admin API routes for intent management.

Provides CRUD endpoints for managing conversational intents with input validation
and pagination support for Lambda deployment.
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Dict, Any
from app.admin.intents import store
from shared.models.intents import Intent

router = APIRouter(prefix="/intents", tags=["intents"])


@router.post("/")
async def create_intent(intent: Intent) -> Dict[str, Any]:
    """
    Create a new intent.
    
    Args:
        intent: Intent data to create
        
    Returns:
        Created intent object
        
    Raises:
        HTTPException: If creation fails
    """
    try:
        intent_dict = intent.model_dump(exclude={"id"})
        created_intent = await store.add_intent(intent_dict)
        return created_intent.model_dump()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/")
async def read_intents(
    skip: int = Query(0, ge=0, description="Number of intents to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of intents to return"),
) -> Dict[str, Any]:
    """
    Get all intents with pagination.
    
    Args:
        skip: Number of intents to skip (default: 0)
        limit: Maximum number of intents to return (default: 100, max: 1000)
        
    Returns:
        Dictionary containing intents list and total count
        
    Raises:
        HTTPException: If retrieval fails
    """
    try:
        intents, total_count = await store.list_intents(skip=skip, limit=limit)
        return {
            "items": [intent.model_dump() for intent in intents],
            "total": total_count,
            "skip": skip,
            "limit": limit,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{intent_id}")
async def read_intent(intent_id: str) -> Dict[str, Any]:
    """
    Get a specific intent by ID.
    
    Args:
        intent_id: The intent ID (MongoDB ObjectId as string)
        
    Returns:
        Intent object
        
    Raises:
        HTTPException: If intent not found or ID is invalid
    """
    try:
        intent = await store.get_intent(intent_id)
        return intent.model_dump()
    except store.ObjectIdError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{intent_id}")
async def update_intent(intent_id: str, intent: Intent) -> Dict[str, str]:
    """
    Update an intent.
    
    Args:
        intent_id: The intent ID (MongoDB ObjectId as string)
        intent: Updated intent data
        
    Returns:
        Status confirmation
        
    Raises:
        HTTPException: If update fails or ID is invalid
    """
    try:
        intent_dict = intent.model_dump(exclude={"id"})
        await store.edit_intent(intent_id, intent_dict)
        return {"status": "success"}
    except store.ObjectIdError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{intent_id}")
async def delete_intent(intent_id: str) -> Dict[str, str]:
    """
    Delete an intent.
    
    Args:
        intent_id: The intent ID (MongoDB ObjectId as string)
        
    Returns:
        Status confirmation
        
    Raises:
        HTTPException: If deletion fails or ID is invalid
    """
    try:
        await store.delete_intent(intent_id)
        return {"status": "success"}
    except store.ObjectIdError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))