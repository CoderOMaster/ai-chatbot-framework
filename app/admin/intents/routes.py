"""Intent CRUD routes with authentication, validation, versioning, and workflow support."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.admin.intents.schemas import Intent
from app.admin.intents import store
from app.admin.intents.exceptions import (
    IntentValidationError,
    IntentNotFoundError,
    IntentVersionError,
    CircularReferenceError,
)
from app.auth import get_current_user
from app.auth.models import User

router = APIRouter(prefix="/intents", tags=["intents"])


async def _validate_circular_references(intent_data: Dict[str, Any], intent_id: Optional[str] = None) -> None:
    """Validate that intent does not have circular references.

    Args:
        intent_data: Intent data to validate
        intent_id: Current intent ID (for updates)

    Raises:
        CircularReferenceError: If circular reference is detected
    """
    # Check for self-references in related intents or parameters
    related_intents = intent_data.get("relatedIntents", [])
    
    if intent_id and intent_id in related_intents:
        raise CircularReferenceError(f"Intent cannot reference itself: {intent_id}")
    
    # Check for circular chains in related intents
    if related_intents:
        visited = set()
        
        async def check_chain(current_id: str, chain: set) -> None:
            if current_id in chain:
                raise CircularReferenceError(
                    f"Circular reference detected in intent chain: {' -> '.join(chain)} -> {current_id}"
                )
            if current_id in visited:
                return
            
            visited.add(current_id)
            chain.add(current_id)
            
            try:
                current_intent = await store.get_intent(current_id)
                current_related = getattr(current_intent, "relatedIntents", [])
                for related_id in current_related:
                    await check_chain(related_id, chain.copy())
            except IntentNotFoundError:
                pass
        
        for related_id in related_intents:
            await check_chain(related_id, {intent_id} if intent_id else set())


@router.post("/", response_model=Intent, status_code=status.HTTP_201_CREATED)
async def create_intent(
    intent: Intent,
    current_user: User = Depends(get_current_user),
) -> Intent:
    """Create a new intent with validation and versioning.
    
    Args:
        intent: Intent data to create
        current_user: Authenticated user
        
    Returns:
        Created Intent object
        
    Raises:
        HTTPException: If validation fails or circular reference detected
    """
    try:
        intent_dict = intent.model_dump(exclude={"id"})
        
        # Validate circular references
        await _validate_circular_references(intent_dict)
        
        # Add metadata
        intent_dict["created_by"] = current_user.id
        intent_dict["status"] = "draft"  # Default to draft status
        
        created_intent = await store.add_intent(intent_dict)
        return created_intent
    except CircularReferenceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Circular reference validation failed: {str(e)}"
        )
    except IntentValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Intent validation failed: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create intent: {str(e)}"
        )


@router.get("/", response_model=Dict[str, Any])
async def read_intents(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get all intents with pagination, search, and filtering.
    
    Args:
        skip: Number of intents to skip
        limit: Maximum number of intents to return
        search: Search term for intent name or intentId
        status_filter: Filter by intent status (draft, published)
        current_user: Authenticated user
        
    Returns:
        Dictionary with intents list and total count
    """
    try:
        filters = {}
        if status_filter:
            filters["status"] = status_filter
        
        intents, total_count = await store.list_intents(
            skip=skip,
            limit=limit,
            search=search,
            filters=filters,
        )
        
        return {
            "data": intents,
            "total": total_count,
            "skip": skip,
            "limit": limit,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve intents: {str(e)}"
        )


@router.get("/{intent_id}", response_model=Intent)
async def read_intent(
    intent_id: str,
    current_user: User = Depends(get_current_user),
) -> Intent:
    """Get a specific intent by ID.
    
    Args:
        intent_id: Intent ID
        current_user: Authenticated user
        
    Returns:
        Intent object
        
    Raises:
        HTTPException: If intent not found
    """
    try:
        intent = await store.get_intent(intent_id)
        return intent
    except IntentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve intent: {str(e)}"
        )


@router.put("/{intent_id}", response_model=Intent)
async def update_intent(
    intent_id: str,
    intent: Intent,
    current_user: User = Depends(get_current_user),
) -> Intent:
    """Update an intent with validation and versioning.
    
    Args:
        intent_id: Intent ID to update
        intent: Updated intent data
        current_user: Authenticated user
        
    Returns:
        Updated Intent object
        
    Raises:
        HTTPException: If validation fails or intent not found
    """
    try:
        intent_dict = intent.model_dump(exclude={"id"})
        
        # Validate circular references
        await _validate_circular_references(intent_dict, intent_id)
        
        # Add metadata
        intent_dict["updated_by"] = current_user.id
        intent_dict["updated_at"] = datetime.utcnow()
        
        updated_intent = await store.edit_intent(intent_id, intent_dict)
        return updated_intent
    except CircularReferenceError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Circular reference validation failed: {str(e)}"
        )
    except IntentValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Intent validation failed: {str(e)}"
        )
    except IntentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update intent: {str(e)}"
        )


@router.delete("/{intent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_intent(
    intent_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete an intent with versioning.
    
    Args:
        intent_id: Intent ID to delete
        current_user: Authenticated user
        
    Raises:
        HTTPException: If intent not found
    """
    try:
        await store.delete_intent(intent_id)
    except IntentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete intent: {str(e)}"
        )


@router.post("/{intent_id}/publish", response_model=Intent)
async def publish_intent(
    intent_id: str,
    current_user: User = Depends(get_current_user),
) -> Intent:
    """Publish a draft intent.
    
    Args:
        intent_id: Intent ID to publish
        current_user: Authenticated user
        
    Returns:
        Published Intent object
        
    Raises:
        HTTPException: If intent not found or already published
    """
    try:
        intent = await store.get_intent(intent_id)
        
        if getattr(intent, "status", None) == "published":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Intent is already published"
            )
        
        update_data = {
            "status": "published",
            "published_at": datetime.utcnow(),
            "published_by": current_user.id,
        }
        
        published_intent = await store.edit_intent(intent_id, update_data)
        return published_intent
    except IntentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to publish intent: {str(e)}"
        )


@router.post("/{intent_id}/unpublish", response_model=Intent)
async def unpublish_intent(
    intent_id: str,
    current_user: User = Depends(get_current_user),
) -> Intent:
    """Unpublish a published intent (revert to draft).
    
    Args:
        intent_id: Intent ID to unpublish
        current_user: Authenticated user
        
    Returns:
        Unpublished Intent object
        
    Raises:
        HTTPException: If intent not found or already draft
    """
    try:
        intent = await store.get_intent(intent_id)
        
        if getattr(intent, "status", None) != "published":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Intent is not published"
            )
        
        update_data = {
            "status": "draft",
            "unpublished_at": datetime.utcnow(),
            "unpublished_by": current_user.id,
        }
        
        unpublished_intent = await store.edit_intent(intent_id, update_data)
        return unpublished_intent
    except IntentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to unpublish intent: {str(e)}"
        )


@router.get("/{intent_id}/history", response_model=List[Dict[str, Any]])
async def get_intent_history(
    intent_id: str,
    limit: int = Query(50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Get version history for an intent.
    
    Args:
        intent_id: Intent ID
        limit: Maximum number of history records
        current_user: Authenticated user
        
    Returns:
        List of version history records
        
    Raises:
        HTTPException: If intent not found
    """
    try:
        history = await store.get_intent_history(intent_id, limit=limit)
        return history
    except IntentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve intent history: {str(e)}"
        )


@router.post("/{intent_id}/rollback/{version_number}", response_model=Intent)
async def rollback_intent_version(
    intent_id: str,
    version_number: int,
    current_user: User = Depends(get_current_user),
) -> Intent:
    """Rollback an intent to a previous version.
    
    Args:
        intent_id: Intent ID
        version_number: Version number to rollback to
        current_user: Authenticated user
        
    Returns:
        Restored Intent object
        
    Raises:
        HTTPException: If version not found or intent not found
    """
    try:
        restored_intent = await store.rollback_intent(intent_id, version_number)
        return restored_intent
    except IntentVersionError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except IntentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rollback intent: {str(e)}"
        )