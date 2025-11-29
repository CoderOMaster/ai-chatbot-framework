from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.admin.integrations.schemas import Integration, IntegrationUpdate
from app.admin.integrations.store import IntegrationRepository
from app.config import app_config
from app.database import create_collection_getter_from_config

router = APIRouter(prefix="/integrations", tags=["integrations"])

_collection_getter = create_collection_getter_from_config(app_config)


def get_integration_repository() -> IntegrationRepository:
    """Provide a repository instance wired to the configured database collections."""

    return IntegrationRepository(_collection_getter)


class IntegrationError(Exception):
    """Base exception raised by integration handlers when a request cannot be fulfilled."""

    status_code: int = 500


class IntegrationNotFoundError(IntegrationError):
    """Raised when an integration lookup returns no matching record."""

    status_code = 404

    def __init__(self, integration_id: str) -> None:
        super().__init__(f"Integration '{integration_id}' not found")
        self.integration_id = integration_id


class IntegrationValidationError(IntegrationError):
    """Raised when a provided integration payload fails validation."""

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)


async def list_integrations_handler(repository: IntegrationRepository) -> list[Integration]:
    """Return every integration defined in the repository."""

    return await repository.list_integrations()


async def get_integration_handler(
    repository: IntegrationRepository,
    integration_id: str,
) -> Integration:
    """Retrieve an integration record by its identifier."""

    integration = await repository.get_integration(integration_id)
    if integration is None:
        raise IntegrationNotFoundError(integration_id)
    return integration


async def update_integration_handler(
    repository: IntegrationRepository,
    integration_id: str,
    integration: IntegrationUpdate,
) -> Integration:
    """Apply updates to an existing integration and return the fresh record."""

    update_payload = integration.model_dump(exclude_unset=True)
    if not update_payload:
        raise IntegrationValidationError("At least one field must be provided for an update")

    updated_integration = await repository.update_integration(integration_id, integration)
    if updated_integration is None:
        raise IntegrationNotFoundError(integration_id)
    return updated_integration


def _to_http_exception(exc: IntegrationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/", response_model=list[Integration])
async def list_integrations(
    repository: IntegrationRepository = Depends(get_integration_repository),
) -> list[Integration]:
    return await list_integrations_handler(repository)


@router.get("/{integration_id}", response_model=Integration)
async def get_integration(
    integration_id: str,
    repository: IntegrationRepository = Depends(get_integration_repository),
) -> Integration:
    try:
        return await get_integration_handler(repository, integration_id)
    except IntegrationError as exc:
        raise _to_http_exception(exc)


@router.put("/{integration_id}", response_model=Integration)
async def update_integration(
    integration_id: str,
    integration: IntegrationUpdate,
    repository: IntegrationRepository = Depends(get_integration_repository),
) -> Integration:
    try:
        return await update_integration_handler(repository, integration_id, integration)
    except IntegrationError as exc:
        raise _to_http_exception(exc)


__all__ = [
    "IntegrationError",
    "IntegrationNotFoundError",
    "IntegrationValidationError",
    "get_integration_handler",
    "list_integrations_handler",
    "update_integration_handler",
    "router",
    "get_integration_repository",
]