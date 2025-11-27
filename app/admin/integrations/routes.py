from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

# Lazy imports via dependency to allow tests to inject a mock store.
from app.admin.integrations import schemas as _schemas

router = APIRouter(prefix="/integrations", tags=["integrations"])


async def get_default_store():
    """FastAPI dependency that returns the real integrations store module.

    Tests can override this dependency to inject a mock store with the same
    async APIs (list_integrations, get_integration, update_integration).
    """
    # Local import to avoid module-level import time coupling
    from app.admin.integrations import store as _store

    return _store


async def require_admin(x_admin: Optional[str] = Header(None)) -> None:
    """Simple role check dependency.

    This enforces that a caller must present an admin indicator header.
    In production this should be replaced by a proper authentication/authorization
    dependency (FastAPI Security/OAuth2/JWT). Keeping a header-based check here
    keeps the route signatures explicit and testable.
    """
    if x_admin is None:
        raise HTTPException(status_code=403, detail="admin privileges required")

    val = str(x_admin).lower()
    if val not in ("1", "true", "yes"):
        raise HTTPException(status_code=403, detail="admin privileges required")


class IntegrationUpdateDTO(BaseModel):
    """DTO for partial updates to an integration.

    Only include the fields that are allowed to be changed via the admin API.
    Fields are optional so callers can send partial updates without overwriting
    unspecified values.
    """

    status: Optional[_schemas.IntegrationStatus] = None
    settings: Optional[Dict[str, Any]] = None


def _mask_sensitive_settings(settings: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a shallow copy of settings where sensitive keys are masked.

    Masked values are replaced with a fixed placeholder so secrets are never
    returned in API responses.
    """
    if settings is None:
        return None

    out: Dict[str, Any] = {}
    for k, v in settings.items():
        if k in _schemas.SENSITIVE_KEYS and v is not None:
            out[k] = "*****"
        else:
            out[k] = v
    return out


def _mask_integration_payload(integration: _schemas.Integration) -> Dict[str, Any]:
    """Serialize an Integration model to a dict and mask sensitive values.

    Returning a plain dict keeps the response shape stable and prevents
    accidental exposure of raw secret values.
    """
    payload = integration.model_dump()
    payload["settings"] = _mask_sensitive_settings(payload.get("settings"))
    return payload


@router.get("/", response_model=List[_schemas.Integration])
async def list_integrations(store=Depends(get_default_store), _admin=Depends(require_admin)):
    """List all active integrations.

    Disabled integrations are intentionally hidden (treated as 404) so that
    consumers cannot discover them via listing endpoints.
    """
    integrations = await store.list_integrations()

    # Filter out disabled integrations to surface them as "not found".
    active = [i for i in integrations if i.status == _schemas.IntegrationStatus.ACTIVE]

    # Mask sensitive fields before returning
    return [_mask_integration_payload(i) for i in active]


@router.get("/{id}", response_model=_schemas.Integration)
async def get_integration(id: str, store=Depends(get_default_store), _admin=Depends(require_admin)):
    """Get a single integration by id.

    Disabled integrations are treated as not found to avoid exposing their
    existence or configuration.
    """
    integration = await store.get_integration(id)
    if not integration or integration.status == _schemas.IntegrationStatus.DISABLED:
        raise HTTPException(status_code=404, detail="Integration not found")

    return _mask_integration_payload(integration)


@router.put("/{id}", response_model=_schemas.Integration)
async def update_integration(
    id: str, update: IntegrationUpdateDTO, store=Depends(get_default_store), _admin=Depends(require_admin)
):
    """Partially update an integration's mutable fields (status, settings).

    Uses a dedicated DTO that only allows partial updates and will not
    accidentally overwrite other stored attributes.
    """
    # The store API expects a model-like object with model_dump(exclude_unset=True).
    # Our DTO is a pydantic model and provides .model_dump, so we can pass it
    # directly. This keeps the store implementation unchanged while allowing
    # request-level validation and partial updates.
    updated = await store.update_integration(id, update)
    if not updated:
        raise HTTPException(status_code=404, detail="Integration not found")

    # If the integration is disabled after the update, expose as not found.
    if updated.status == _schemas.IntegrationStatus.DISABLED:
        raise HTTPException(status_code=404, detail="Integration not found")

    return _mask_integration_payload(updated)