"""Entity management routes with authentication, validation, pagination, and filtering."""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.admin.entities import store
from app.admin.entities.schemas import Entity, EntityCreate, EntityUpdate
from app.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/entities", tags=["entities"])


async def get_user_id(current_user: dict = Depends(get_current_user)) -> str:
    """Extract user ID from authenticated user.
    
    Args:
        current_user: Current authenticated user from dependency
        
    Returns:
        User ID string
        
    Raises:
        HTTPException: If user ID is missing
    """
    user_id = current_user.get("id") or current_user.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User ID not found in token",
        )
    return user_id


@router.post(
    "/",
    response_model=Entity,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new entity",
)
async def create_entity(
    entity: EntityCreate,
    user_id: str = Depends(get_user_id),
) -> Entity:
    """Create a new entity with validation and audit logging.
    
    Args:
        entity: Entity data to create
        user_id: Authenticated user ID
        
    Returns:
        Created entity with ID
        
    Raises:
        HTTPException: If validation fails
    """
    try:
        entity_dict = entity.model_dump()
        created_entity = await store.add_entity(entity_dict, user_id=user_id)
        logger.info(f"Entity created by user {user_id}: {created_entity.id}")
        return created_entity
    except ValueError as e:
        logger.warning(f"Validation error during entity creation: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error creating entity: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create entity",
        )


@router.get(
    "/",
    response_model=dict,
    summary="List entities with pagination, filtering, and sorting",
)
async def read_entities(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    sort_by: Optional[str] = Query(
        "created_at",
        description="Field to sort by (name, created_at, updated_at)",
    ),
    sort_order: str = Query("desc", regex="^(asc|desc)$", description="Sort order"),
    name_filter: Optional[str] = Query(None, description="Filter by entity name (partial match)"),
    user_id: str = Depends(get_user_id),
) -> dict:
    """List entities with pagination, filtering, and sorting.
    
    Args:
        page: Page number (1-indexed)
        page_size: Number of items per page
        sort_by: Field to sort by
        sort_order: Sort order (asc or desc)
        name_filter: Optional name filter for partial matching
        user_id: Authenticated user ID
        
    Returns:
        Dictionary with entities list, total count, and pagination info
        
    Raises:
        HTTPException: If invalid parameters provided
    """
    try:
        # Validate sort_by parameter
        valid_sort_fields = {"name", "created_at", "updated_at"}
        if sort_by not in valid_sort_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid sort_by. Must be one of: {', '.join(valid_sort_fields)}",
            )
        
        entities, total_count = await store.list_entities(
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            name_filter=name_filter,
        )
        
        total_pages = (total_count + page_size - 1) // page_size
        
        logger.debug(f"Listed entities by user {user_id}: page {page}, total {total_count}")
        
        return {
            "data": entities,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": total_pages,
            },
        }
    except ValueError as e:
        logger.warning(f"Validation error during entity listing: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error listing entities: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list entities",
        )


@router.get(
    "/{entity_id}",
    response_model=Entity,
    summary="Get a specific entity by ID",
)
async def read_entity(
    entity_id: str,
    user_id: str = Depends(get_user_id),
) -> Entity:
    """Get a specific entity by ID.
    
    Args:
        entity_id: Entity ID to retrieve
        user_id: Authenticated user ID
        
    Returns:
        Entity object
        
    Raises:
        HTTPException: If entity not found
    """
    try:
        entity = await store.get_entity(entity_id)
        logger.debug(f"Retrieved entity {entity_id} by user {user_id}")
        return entity
    except ValueError as e:
        logger.warning(f"Entity not found: {entity_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error retrieving entity {entity_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve entity",
        )


@router.put(
    "/{entity_id}",
    response_model=Entity,
    summary="Update an entity",
)
async def update_entity(
    entity_id: str,
    entity: EntityUpdate,
    user_id: str = Depends(get_user_id),
) -> Entity:
    """Update an entity with validation and audit logging.
    
    Args:
        entity_id: Entity ID to update
        entity: Updated entity data
        user_id: Authenticated user ID
        
    Returns:
        Updated entity object
        
    Raises:
        HTTPException: If validation fails or entity not found
    """
    try:
        entity_dict = entity.model_dump(exclude_unset=True)
        updated_entity = await store.edit_entity(entity_id, entity_dict, user_id=user_id)
        logger.info(f"Entity updated by user {user_id}: {entity_id}")
        return updated_entity
    except ValueError as e:
        logger.warning(f"Validation error or entity not found: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if "not found" in str(e).lower() else status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error updating entity {entity_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update entity",
        )


@router.delete(
    "/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an entity",
)
async def delete_entity(
    entity_id: str,
    user_id: str = Depends(get_user_id),
) -> None:
    """Soft delete an entity (marks as deleted instead of removing).
    
    Args:
        entity_id: Entity ID to delete
        user_id: Authenticated user ID
        
    Raises:
        HTTPException: If entity not found
    """
    try:
        await store.delete_entity(entity_id, user_id=user_id)
        logger.info(f"Entity deleted by user {user_id}: {entity_id}")
    except ValueError as e:
        logger.warning(f"Entity not found: {entity_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error deleting entity {entity_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete entity",
        )


@router.post(
    "/{entity_id}/restore",
    response_model=Entity,
    summary="Restore a deleted entity",
)
async def restore_entity(
    entity_id: str,
    user_id: str = Depends(get_user_id),
) -> Entity:
    """Restore a soft-deleted entity.
    
    Args:
        entity_id: Entity ID to restore
        user_id: Authenticated user ID
        
    Returns:
        Restored entity object
        
    Raises:
        HTTPException: If entity not found or not deleted
    """
    try:
        restored_entity = await store.restore_entity(entity_id, user_id=user_id)
        logger.info(f"Entity restored by user {user_id}: {entity_id}")
        return restored_entity
    except ValueError as e:
        logger.warning(f"Error restoring entity: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if "not found" in str(e).lower() else status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error restoring entity {entity_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to restore entity",
        )


@router.post(
    "/batch/import",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Bulk import entities",
)
async def bulk_import_entities(
    entities: List[EntityCreate],
    user_id: str = Depends(get_user_id),
) -> dict:
    """Bulk import multiple entities with validation.
    
    Args:
        entities: List of entities to import
        user_id: Authenticated user ID
        
    Returns:
        Dictionary with created entity IDs and import statistics
        
    Raises:
        HTTPException: If validation fails or import fails
    """
    try:
        if not entities:
            raise ValueError("At least one entity is required for bulk import")
        
        if len(entities) > 1000:
            raise ValueError("Maximum 1000 entities per bulk import")
        
        entity_dicts = [entity.model_dump() for entity in entities]
        created_ids = await store.bulk_import_entities(entity_dicts, user_id=user_id)
        
        logger.info(f"Bulk import completed by user {user_id}: {len(created_ids)} entities")
        
        return {
            "created_count": len(created_ids),
            "created_ids": created_ids,
            "status": "success",
        }
    except ValueError as e:
        logger.warning(f"Validation error during bulk import: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error during bulk import: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to import entities",
        )


@router.get(
    "/audit/log",
    response_model=dict,
    summary="Get audit log entries",
)
async def get_audit_log(
    entity_id: Optional[str] = Query(None, description="Filter by entity ID"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum entries to return"),
    user_id: str = Depends(get_user_id),
) -> dict:
    """Retrieve audit log entries with optional filtering.
    
    Args:
        entity_id: Optional entity ID to filter by
        action: Optional action type to filter by
        limit: Maximum number of entries to return
        user_id: Authenticated user ID
        
    Returns:
        Dictionary with audit log entries
        
    Raises:
        HTTPException: If retrieval fails
    """
    try:
        entries = await store.get_audit_log(
            entity_id=entity_id,
            action=action,
            limit=limit,
        )
        
        logger.debug(f"Audit log retrieved by user {user_id}: {len(entries)} entries")
        
        return {
            "entries": entries,
            "count": len(entries),
        }
    except Exception as e:
        logger.error(f"Error retrieving audit log: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve audit log",
        )