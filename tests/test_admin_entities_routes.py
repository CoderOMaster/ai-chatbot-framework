from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from app.admin.entities import routes
from app.admin.entities.routes import (
    create_entity_handler,
    delete_entity_handler,
    get_entity_repository,
    list_entities_handler,
    read_entity_handler,
    update_entity_handler,
)
from app.admin.entities.schemas import Entity, EntityValue
from app.admin.entities.store import EntityRepository, MongoEntityRepository


@pytest.fixture
def sample_entity() -> Entity:
    """Provide a sample Entity instance that mirrors production payloads."""

    return Entity(
        name="a_sample_entity",
        entity_values=[EntityValue(value="primary", synonyms=["alias"])],
    )


@pytest.fixture
def repository() -> Mock:
    """Create a mock repository implementing the EntityRepository contract."""

    repo: Mock = Mock(spec=EntityRepository)
    repo.add_entity = AsyncMock()
    repo.list_entities = AsyncMock()
    repo.get_entity = AsyncMock()
    repo.edit_entity = AsyncMock()
    repo.delete_entity = AsyncMock()
    return repo


@pytest.mark.asyncio
async def test_create_entity_handler_success(repository: Mock, sample_entity: Entity) -> None:
    """Verify that the handler forwards the payload without the ID and returns the repository response."""

    repository.add_entity.return_value = sample_entity

    result = await create_entity_handler(repository, sample_entity)

    expected_payload = sample_entity.model_dump(exclude={"id"})
    repository.add_entity.assert_awaited_once_with(expected_payload)
    assert result is sample_entity


@pytest.mark.asyncio
async def test_create_entity_handler_propagates_failure(repository: Mock, sample_entity: Entity) -> None:
    """Ensure errors raised by the repository bubble up to the caller."""

    repository.add_entity.side_effect = RuntimeError("injected failure")

    with pytest.raises(RuntimeError):
        await create_entity_handler(repository, sample_entity)


@pytest.mark.asyncio
async def test_list_entities_handler_returns_entities(repository: Mock, sample_entity: Entity) -> None:
    """Confirm that the handler returns the list produced by the repository."""

    repository.list_entities.return_value = [sample_entity]

    result = await list_entities_handler(repository)

    repository.list_entities.assert_awaited_once()
    assert result == [sample_entity]


@pytest.mark.asyncio
async def test_list_entities_handler_handles_empty(repository: Mock) -> None:
    """Validate that an empty list is just passed through without modification."""

    repository.list_entities.return_value = []

    result = await list_entities_handler(repository)

    repository.list_entities.assert_awaited_once()
    assert result == []


@pytest.mark.asyncio
async def test_read_entity_handler_returns_entity(repository: Mock, sample_entity: Entity) -> None:
    """Assert that a repository lookup produces the expected Entity."""

    repository.get_entity.return_value = sample_entity

    result = await read_entity_handler(repository, "entity-id")

    repository.get_entity.assert_awaited_once_with("entity-id")
    assert result is sample_entity


@pytest.mark.asyncio
async def test_read_entity_handler_propagates_missing(repository: Mock) -> None:
    """Check that repository errors are not swallowed by the handler."""

    repository.get_entity.side_effect = KeyError("missing")

    with pytest.raises(KeyError):
        await read_entity_handler(repository, "entity-id")


@pytest.mark.asyncio
async def test_update_entity_handler_success(repository: Mock, sample_entity: Entity) -> None:
    """Verify the handler normalizes payloads and reports a success status."""

    result = await update_entity_handler(repository, "entity-id", sample_entity)

    expected_payload = sample_entity.model_dump(exclude={"id"})
    repository.edit_entity.assert_awaited_once_with("entity-id", expected_payload)
    assert result == {"status": "success"}


@pytest.mark.asyncio
async def test_update_entity_handler_propagates_failure(repository: Mock, sample_entity: Entity) -> None:
    """Ensure update failures from the repository are surfaced."""

    repository.edit_entity.side_effect = ValueError("update failed")

    with pytest.raises(ValueError):
        await update_entity_handler(repository, "entity-id", sample_entity)


@pytest.mark.asyncio
async def test_delete_entity_handler_success(repository: Mock) -> None:
    """Ensure the delete handler returns the expected status dictionary."""

    result = await delete_entity_handler(repository, "entity-id")

    repository.delete_entity.assert_awaited_once_with("entity-id")
    assert result == {"status": "success"}


@pytest.mark.asyncio
async def test_delete_entity_handler_propagates_failure(repository: Mock) -> None:
    """Confirm that deletion errors propagate to the caller rather than being swallowed."""

    repository.delete_entity.side_effect = PermissionError("cannot delete")

    with pytest.raises(PermissionError):
        await delete_entity_handler(repository, "entity-id")


def test_get_entity_repository_builds_mongo_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate that the router builds a MongoEntityRepository via the injected collection getter."""

    fake_collection: Any = object()
    captured_names: list[str] = []

    def fake_getter(name: str) -> Any:
        captured_names.append(name)
        return fake_collection

    monkeypatch.setattr(routes, "_collection_getter", fake_getter)

    repository_instance = get_entity_repository()

    assert isinstance(repository_instance, MongoEntityRepository)
    assert captured_names == ["entities"]
    assert repository_instance._collection is fake_collection