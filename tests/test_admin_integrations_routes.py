import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock

from app.admin.integrations.routes import (
    IntegrationError,
    IntegrationNotFoundError,
    IntegrationValidationError,
    get_integration_handler,
    list_integrations_handler,
    update_integration_handler,
    _to_http_exception,
)
from app.admin.integrations.schemas import Integration, IntegrationUpdate
from app.admin.integrations.store import IntegrationRepository


@pytest.fixture
def repository() -> AsyncMock:
    """Provide a mock integration repository for each async handler test."""
    return AsyncMock(spec=IntegrationRepository)


def _build_integration() -> Integration:
    return Integration(
        id="sample",
        name="Sample Integration",
        description="A sample integration",
        status=True,
        settings={"key": "value"},
    )


def _build_update() -> IntegrationUpdate:
    return IntegrationUpdate(
        id="sample",
        name="Sample Update",
        description="Updated description",
        status=False,
        settings={"updated": True},
    )


@pytest.mark.asyncio
async def test_list_integrations_handler_returns_repository_results(repository: AsyncMock) -> None:
    """list_integrations_handler should return whatever the repository emits."""

    expected = [_build_integration()]
    repository.list_integrations.return_value = expected

    result = await list_integrations_handler(repository)

    assert result == expected
    repository.list_integrations.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_integration_handler_returns_integration(repository: AsyncMock) -> None:
    """Should yield the integration when the repository can resolve the identifier."""

    expected = _build_integration()
    repository.get_integration.return_value = expected

    result = await get_integration_handler(repository, "sample")

    assert result == expected
    repository.get_integration.assert_awaited_once_with("sample")


@pytest.mark.asyncio
async def test_get_integration_handler_raises_not_found_when_missing(repository: AsyncMock) -> None:
    """Should raise IntegrationNotFoundError if the repository returns None."""

    repository.get_integration.return_value = None

    with pytest.raises(IntegrationNotFoundError) as exc_info:
        await get_integration_handler(repository, "missing")

    assert exc_info.value.integration_id == "missing"
    assert exc_info.value.status_code == 404
    repository.get_integration.assert_awaited_once_with("missing")


@pytest.mark.asyncio
async def test_update_integration_handler_applies_updates(repository: AsyncMock) -> None:
    """Should forward the payload to repository.update_integration and return the refreshed record."""

    expected = _build_integration()
    repository.update_integration.return_value = expected
    payload = _build_update()

    result = await update_integration_handler(repository, "sample", payload)

    assert result == expected
    repository.update_integration.assert_awaited_once_with("sample", payload)


class _EmptyUpdate:
    def model_dump(self, **_: object) -> dict[str, object]:  # type: ignore[override]
        return {}


@pytest.mark.asyncio
async def test_update_integration_handler_requires_payload(repository: AsyncMock) -> None:
    """Should raise IntegrationValidationError when the request does not provide any fields to update."""

    payload = _EmptyUpdate()  # type: ignore[arg-type]

    with pytest.raises(IntegrationValidationError) as exc_info:
        await update_integration_handler(repository, "sample", payload)  # type: ignore[arg-type]

    assert str(exc_info.value) == "At least one field must be provided for an update"
    repository.update_integration.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_integration_handler_raises_not_found_when_update_missing(repository: AsyncMock) -> None:
    """Should bubble up a not found error when the repository cannot update the record."""

    repository.update_integration.return_value = None
    payload = _build_update()

    with pytest.raises(IntegrationNotFoundError) as exc_info:
        await update_integration_handler(repository, "missing", payload)

    assert exc_info.value.integration_id == "missing"
    repository.update_integration.assert_awaited_once_with("missing", payload)


def test_to_http_exception_preserves_status_codes() -> None:
    """The HTTP exception produced should mirror the integration error metadata."""

    error = IntegrationNotFoundError("sample")
    http_exc = _to_http_exception(error)

    assert isinstance(http_exc, HTTPException)
    assert http_exc.status_code == 404
    assert http_exc.detail == "Integration 'sample' not found"


@pytest.mark.asyncio
async def test_update_integration_handler_type_error_from_repository_raises_integration_error(
    repository: AsyncMock,
) -> None:
    """If the repository surfaces an unexpected error the handler should not swallow it."""

    repository.update_integration.side_effect = IntegrationError("boom")
    payload = _build_update()

    with pytest.raises(IntegrationError):
        await update_integration_handler(repository, "sample", payload)

    repository.update_integration.assert_awaited_once_with("sample", payload)