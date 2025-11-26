from typing import List

from fastapi import APIRouter, HTTPException, Path

from . import store
from .schemas import Integration, IntegrationUpdate

router = APIRouter(prefix="/integrations", tags=["integrations"])


def _validate_integration_id(integration_id: str) -> str:
    """Validate integration ID format and existence.
    
    Args:
        integration_id: The integration identifier to validate.
        
    Returns:
        The validated integration ID.
        
    Raises:
        HTTPException: If ID is invalid or empty.
    """
    if not integration_id or not integration_id.strip():
        raise HTTPException(
            status_code=400,
            detail="Integration ID cannot be empty"
        )
    return integration_id.strip()


def _raise_not_found(integration_id: str) -> None:
    """Raise a standardized 404 error for missing integrations.
    
    Args:
        integration_id: The integration identifier that was not found.
        
    Raises:
        HTTPException: Always raises 404 with standardized detail message.
    """
    raise HTTPException(
        status_code=404,
        detail=f"Integration '{integration_id}' not found"
    )


@router.get("/", response_model=List[Integration])
async def list_integrations():
    """List all available integrations."""
    return await store.list_integrations()


@router.get("/{id}", response_model=Integration)
async def get_integration(id: str = Path(..., min_length=1)):
    """Get a specific integration by ID.
    
    Args:
        id: The integration identifier.
        
    Returns:
        The requested Integration object.
        
    Raises:
        HTTPException: 400 if ID is invalid, 404 if not found.
    """
    validated_id = _validate_integration_id(id)
    integration = await store.get_integration(validated_id)
    if not integration:
        _raise_not_found(validated_id)
    return integration


@router.put("/{id}", response_model=Integration)
async def update_integration(
    id: str = Path(..., min_length=1),
    integration: IntegrationUpdate = None
):
    """Update an integration's status and settings.
    
    Args:
        id: The integration identifier.
        integration: The update payload with new settings.
        
    Returns:
        The updated Integration object.
        
    Raises:
        HTTPException: 400 if ID is invalid, 404 if not found.
    """
    validated_id = _validate_integration_id(id)
    updated_integration = await store.update_integration(validated_id, integration)
    if not updated_integration:
        _raise_not_found(validated_id)
    return updated_integration