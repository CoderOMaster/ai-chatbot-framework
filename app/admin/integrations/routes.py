"""Integration management routes with authentication, validation, and audit logging."""
import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Header
from app.admin.integrations import store
from app.admin.integrations.schemas import Integration, IntegrationUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


async def verify_auth_token(authorization: Optional[str] = Header(None)) -> str:
    """Verify authentication token from request header.
    
    Args:
        authorization: Authorization header value
        
    Returns:
        User ID extracted from token
        
    Raises:
        HTTPException: If authentication fails
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    try:
        # Extract bearer token
        if not authorization.startswith("Bearer "):
            raise ValueError("Invalid authorization format")
        
        token = authorization[7:]  # Remove "Bearer " prefix
        
        # TODO: Implement actual token validation with JWT or similar
        # For now, validate token is not empty
        if not token or len(token) < 10:
            raise ValueError("Invalid token format")
        
        # Extract user ID from token (placeholder implementation)
        user_id = token.split(".")[0] if "." in token else "unknown"
        return user_id
    except Exception as e:
        logger.warning(f"Authentication failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")


@router.get("/", response_model=List[Integration])
async def list_integrations(user_id: str = Depends(verify_auth_token)) -> List[Integration]:
    """List all available integrations.
    
    Args:
        user_id: Authenticated user ID
        
    Returns:
        List of integrations
        
    Raises:
        HTTPException: If retrieval fails
    """
    try:
        logger.info(f"User {user_id} listing integrations")
        return await store.list_integrations()
    except RuntimeError as e:
        logger.error(f"Failed to list integrations: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve integrations")


@router.get("/{id}", response_model=Integration)
async def get_integration(id: str, user_id: str = Depends(verify_auth_token)) -> Integration:
    """Get a specific integration by ID.
    
    Args:
        id: Integration ID
        user_id: Authenticated user ID
        
    Returns:
        Integration object
        
    Raises:
        HTTPException: If integration not found or retrieval fails
    """
    try:
        logger.info(f"User {user_id} retrieving integration {id}")
        integration = await store.get_integration(id)
        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found")
        return integration
    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"Failed to get integration {id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve integration")


@router.post("/{id}/test-connection", response_model=Dict[str, Any])
async def test_integration_connection(id: str, user_id: str = Depends(verify_auth_token)) -> Dict[str, Any]:
    """Test connection for an integration.
    
    Args:
        id: Integration ID
        user_id: Authenticated user ID
        
    Returns:
        Connection test result
        
    Raises:
        HTTPException: If test fails or integration not found
    """
    try:
        logger.info(f"User {user_id} testing connection for integration {id}")
        result = await store.test_connection(id)
        return result
    except ValueError as e:
        logger.warning(f"Connection test validation failed for {id}: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Connection test failed for {id}: {e}")
        raise HTTPException(status_code=500, detail="Connection test failed")


@router.put("/{id}", response_model=Integration)
async def update_integration(
    id: str,
    integration: IntegrationUpdate,
    user_id: str = Depends(verify_auth_token),
) -> Integration:
    """Update an integration's status and settings.
    
    Args:
        id: Integration ID
        integration: Update data
        user_id: Authenticated user ID
        
    Returns:
        Updated integration
        
    Raises:
        HTTPException: If update fails or integration not found
    """
    try:
        logger.info(f"User {user_id} updating integration {id}")
        
        # Validate webhook settings if provided
        if integration.settings and isinstance(integration.settings, dict):
            if "webhook_url" in integration.settings:
                _validate_webhook_url(integration.settings["webhook_url"])
        
        updated_integration = await store.update_integration(id, integration, user_id=user_id)
        if not updated_integration:
            raise HTTPException(status_code=404, detail="Integration not found")
        
        logger.info(f"Integration {id} successfully updated by user {user_id}")
        return updated_integration
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Validation error updating integration {id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error(f"Failed to update integration {id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update integration")


def _validate_webhook_url(webhook_url: str) -> None:
    """Validate webhook URL format and security.
    
    Args:
        webhook_url: Webhook URL to validate
        
    Raises:
        ValueError: If webhook URL is invalid
    """
    if not webhook_url:
        raise ValueError("Webhook URL cannot be empty")
    
    if not isinstance(webhook_url, str):
        raise ValueError("Webhook URL must be a string")
    
    # Validate URL format
    if not webhook_url.startswith(("http://", "https://")):
        raise ValueError("Webhook URL must start with http:// or https://")
    
    # Ensure HTTPS for production
    if webhook_url.startswith("http://") and not webhook_url.startswith("http://localhost"):
        logger.warning(f"Webhook URL uses insecure HTTP: {webhook_url}")
        raise ValueError("Webhook URL must use HTTPS for security")
    
    # Basic length validation
    if len(webhook_url) > 2048:
        raise ValueError("Webhook URL is too long")