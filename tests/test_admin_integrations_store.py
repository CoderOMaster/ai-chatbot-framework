import pytest
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, call

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument

from app.admin.integrations import store as integration_store
from app.admin.integrations.schemas import Integration, IntegrationUpdate
from app.admin.integrations.store import DEFAULT_INTEGRATIONS, IntegrationRepository


@pytest.fixture
def sample_integrations_document() -> dict[str, Any]:
    return {
        "id": "facebook",
        "name": "Facebook Messenger",
        "description": "Connect via Facebook",
        "status": True,
        "settings": {"verify": "token"},
    }


@pytest.fixture
def mock_collection(sample_integrations_document: dict[str, Any]) -> AsyncIOMotorCollection:
    collection = MagicMock(spec=AsyncIOMotorCollection)
    collection.find_one = AsyncMock()
    collection.find_one_and_update = AsyncMock()
    collection.update_one = AsyncMock()

    cursor = AsyncMock()
    cursor.to_list.return_value = [sample_integrations_document]
    collection.find.return_value = cursor

    return collection


@pytest.fixture
def collection_getter(mock_collection: AsyncIOMotorCollection) -> Callable[[str], AsyncIOMotorCollection]:
    def _getter(_: str) -> AsyncIOMotorCollection:
        return mock_collection

    return _getter


@pytest.fixture
def repository(collection_getter: Callable[[str], AsyncIOMotorCollection]) -> IntegrationRepository:
    return IntegrationRepository(collection_getter)


@pytest.mark.asyncio
async def test_list_integrations_returns_models(
    repository: IntegrationRepository, mock_collection: AsyncIOMotorCollection, sample_integrations_document: dict[str, Any]
) -> None:
    """Listing integrations should return typed Integration models derived from Mongo documents."""

    integrations = await repository.list_integrations()

    assert integrations == [Integration(**sample_integrations_document)]
    mock_collection.find.assert_called_once()
    mock_collection.find.return_value.to_list.assert_awaited_once_with(length=None)


@pytest.mark.asyncio
async def test_get_integration_returns_document_when_present(
    repository: IntegrationRepository, mock_collection: AsyncIOMotorCollection, sample_integrations_document: dict[str, Any]
) -> None:
    """Getting an integration should return a typed model when persistence has the record."""

    mock_collection.find_one.return_value = sample_integrations_document

    result = await repository.get_integration("facebook")

    assert result == Integration(**sample_integrations_document)
    mock_collection.find_one.assert_awaited_once_with({"id": "facebook"})


@pytest.mark.asyncio
async def test_get_integration_returns_none_when_absent(
    repository: IntegrationRepository, mock_collection: AsyncIOMotorCollection
) -> None:
    """A missing record should yield None rather than raising an exception."""

    mock_collection.find_one.return_value = None

    result = await repository.get_integration("facebook")

    assert result is None
    mock_collection.find_one.assert_awaited_once_with({"id": "facebook"})


@pytest.mark.asyncio
async def test_update_integration_applies_updates_when_data_provided(
    repository: IntegrationRepository, mock_collection: AsyncIOMotorCollection
) -> None:
    """Updating an integration should send the $set update and return the refreshed document."""

    updated_document = {
        "id": "facebook",
        "name": "Updated Messenger",
        "description": "Updated",
        "status": True,
        "settings": {"verify": "changed"},
    }
    mock_collection.find_one_and_update.return_value = updated_document

    update_payload = IntegrationUpdate(
        id="facebook",
        name="Updated Messenger",
        description="Updated",
        status=True,
        settings={"verify": "changed"},
    )

    result = await repository.update_integration("facebook", update_payload)

    expected_update = update_payload.model_dump(exclude_unset=True)
    mock_collection.find_one_and_update.assert_awaited_once_with(
        {"id": "facebook"},
        {"$set": expected_update},
        return_document=ReturnDocument.AFTER,
    )
    assert result == Integration(**updated_document)


@pytest.mark.asyncio
async def test_update_integration_returns_none_when_not_found(
    repository: IntegrationRepository, mock_collection: AsyncIOMotorCollection
) -> None:
    """The update operation should return None when the document is missing."""

    mock_collection.find_one_and_update.return_value = None

    update_payload = IntegrationUpdate(
        id="facebook",
        name="Facebook Messenger",
        description="Connect via Facebook",
        status=True,
        settings={"verify": "token"},
    )

    result = await repository.update_integration("facebook", update_payload)

    assert result is None


@pytest.mark.asyncio
async def test_update_integration_short_circuits_when_no_data(
    repository: IntegrationRepository, mock_collection: AsyncIOMotorCollection, sample_integrations_document: dict[str, Any]
) -> None:
    """No database mutation should happen when the update payload serializes to an empty dict."""

    repository.get_integration = AsyncMock(return_value=Integration(**sample_integrations_document))
    empty_payload = IntegrationUpdate.model_construct()

    result = await repository.update_integration("facebook", empty_payload)

    repository.get_integration.assert_awaited_once_with("facebook")
    mock_collection.find_one_and_update.assert_not_called()
    assert result == Integration(**sample_integrations_document)


@pytest.mark.asyncio
async def test_ensure_default_integrations_upserts_every_definition(
    repository: IntegrationRepository, mock_collection: AsyncIOMotorCollection
) -> None:
    """Each default integration definition should be upserted with $setOnInsert semantics."""

    await repository.ensure_default_integrations()

    expected_calls = [
        call({"id": integration["id"]}, {"$setOnInsert": integration}, upsert=True)
        for integration in DEFAULT_INTEGRATIONS
    ]
    mock_collection.update_one.assert_has_awaits(expected_calls)


@pytest.mark.asyncio
async def test_module_list_integrations_delegates_to_repository() -> None:
    """The module-level list function should use the provided repository instance."""

    repo = AsyncMock(spec=IntegrationRepository)
    repo.list_integrations.return_value = [Integration(**DEFAULT_INTEGRATIONS[0])]

    result = await integration_store.list_integrations(repository=repo)

    repo.list_integrations.assert_awaited_once()
    assert result == [Integration(**DEFAULT_INTEGRATIONS[0])]


@pytest.mark.asyncio
async def test_module_get_integration_delegates_to_repository() -> None:
    """The module helper for get should rely on the injected repository."""

    repo = AsyncMock(spec=IntegrationRepository)
    repo.get_integration.return_value = Integration(**DEFAULT_INTEGRATIONS[0])

    result = await integration_store.get_integration("facebook", repository=repo)

    repo.get_integration.assert_awaited_once_with("facebook")
    assert result == Integration(**DEFAULT_INTEGRATIONS[0])


@pytest.mark.asyncio
async def test_module_update_integration_delegates_to_repository() -> None:
    """Updates performed through the helper should return whatever the repository returns."""

    repo = AsyncMock(spec=IntegrationRepository)
    repo.update_integration.return_value = Integration(**DEFAULT_INTEGRATIONS[0])
    payload = IntegrationUpdate.model_construct()

    result = await integration_store.update_integration("facebook", payload, repository=repo)

    repo.update_integration.assert_awaited_once_with("facebook", payload)
    assert result == Integration(**DEFAULT_INTEGRATIONS[0])


@pytest.mark.asyncio
async def test_module_ensure_default_integrations_delegates_to_repository() -> None:
    """The bootstrapping helper should forward to the repository implementation."""

    repo = AsyncMock(spec=IntegrationRepository)

    await integration_store.ensure_default_integrations(repository=repo)

    repo.ensure_default_integrations.assert_awaited_once()