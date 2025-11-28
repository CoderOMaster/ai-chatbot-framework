from __future__ import annotations

from app.admin.integrations.schemas import Integration, IntegrationUpdate
from app.admin.integrations.store import IntegrationRepository


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


__all__ = [
    "IntegrationError",
    "IntegrationNotFoundError",
    "IntegrationValidationError",
    "get_integration_handler",
    "list_integrations_handler",
    "update_integration_handler",
]