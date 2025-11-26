from typing import List, Any

from .store import IntegrationRepository
from .schemas import Integration, IntegrationUpdate


class NotFoundError(Exception):
    """Raised when a requested resource cannot be found."""


class BadRequestError(ValueError):
    """Raised when request validation fails."""


async def list_integrations(repo: IntegrationRepository) -> List[Integration]:
    """Return all integrations using the provided repository.

    Args:
        repo: An IntegrationRepository instance responsible for data access.

    Returns:
        A list of Integration models.
    """
    return await repo.list_integrations()


async def get_integration(id: str, repo: IntegrationRepository) -> Integration:
    """Retrieve a single integration by id.

    Validates the id and raises BadRequestError for invalid inputs or
    NotFoundError if no integration with the given id exists.

    Args:
        id: The integration identifier to look up.
        repo: An IntegrationRepository instance.

    Returns:
        The Integration instance for the provided id.

    Raises:
        BadRequestError: If the id is empty or invalid.
        NotFoundError: If no integration exists with the given id.
    """
    if not isinstance(id, str) or not id.strip():
        raise BadRequestError("id is required and must be a non-empty string")

    integration = await repo.get_integration(id)
    if integration is None:
        raise NotFoundError(f"Integration not found: {id}")
    return integration


async def update_integration(id: str, integration: IntegrationUpdate, repo: IntegrationRepository) -> Integration:
    """Update an integration's fields using the provided repository.

    Performs basic validation on inputs and ensures at least one updatable
    field is present in the provided IntegrationUpdate model. Raises
    BadRequestError for invalid payloads and NotFoundError when the target
    resource does not exist.

    Args:
        id: The identifier of the integration to update.
        integration: A Pydantic IntegrationUpdate model containing fields to update.
        repo: An IntegrationRepository instance.

    Returns:
        The updated Integration model.

    Raises:
        BadRequestError: If inputs are invalid or no updatable fields were provided.
        NotFoundError: If the integration does not exist.
    """
    # Basic id validation
    if not isinstance(id, str) or not id.strip():
        raise BadRequestError("id is required and must be a non-empty string")

    # Ensure we received a Pydantic model (duck-typed) and that there is at
    # least one field to update.
    try:
        update_payload = integration.model_dump(exclude_unset=True)  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover - defensive
        raise BadRequestError("Invalid integration payload") from exc

    if not update_payload:
        raise BadRequestError("No updatable fields provided in payload")

    updated = await repo.update_integration(id, integration)
    if updated is None:
        raise NotFoundError(f"Integration not found: {id}")
    return updated