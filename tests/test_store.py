import pytest
from bson import ObjectId
from unittest.mock import AsyncMock, MagicMock

from app.admin.entities import store
from app.admin.entities.schemas import Entity, EntityValue


class FakeUpdateResult:
    """Utility for mocking pymongo update result metadata."""

    def __init__(self, upserted_id: ObjectId | None) -> None:
        self.upserted_id = upserted_id


@pytest.fixture
def sample_entity_payload() -> dict:
    """Provide a minimal payload usable for entity creation."""

    return {
        "name": "sample",
        "entity_values": [
            {"value": "canonical", "synonyms": ["alias-one", "alias-two"]}
        ],
    }


@pytest.fixture
def sample_entity() -> Entity:
    """Create an Entity model instance representing persisted data."""

    return Entity(
        name="sample",
        entity_values=[
            EntityValue(value="canonical", synonyms=["alias-one", "alias-two"])
        ],
    )


@pytest.mark.asyncio
async def test_add_entity_validates_created_document(
    monkeypatch, sample_entity_payload: dict, sample_entity: Entity
) -> None:
    """Ensure add_entity inserts the payload and re-fetches via get_entity."""

    collection = AsyncMock()
    inserted_id = ObjectId()
    collection.insert_one.return_value = MagicMock(inserted_id=inserted_id)
    get_entity_mock = AsyncMock(return_value=sample_entity)
    monkeypatch.setattr(store, "get_entity", get_entity_mock)

    persisted = await store.add_entity(collection, sample_entity_payload)

    assert persisted is sample_entity
    collection.insert_one.assert_awaited_once_with(sample_entity_payload)
    get_entity_mock.assert_awaited_once_with(collection, str(inserted_id))


@pytest.mark.asyncio
async def test_get_entity_returns_valid_model() -> None:
    """Calling get_entity should return a validated Entity instance using the provided ID."""

    collection = AsyncMock()
    entity_id = ObjectId()
    document = {
        "_id": entity_id,
        "name": "entity",
        "entity_values": [],
    }
    collection.find_one.return_value = document

    result = await store.get_entity(collection, str(entity_id))

    assert isinstance(result, Entity)
    assert result.name == "entity"
    assert str(result.id) == str(entity_id)
    collection.find_one.assert_awaited_once_with({"_id": entity_id})


@pytest.mark.asyncio
async def test_list_entities_streams_document_cursor() -> None:
    """list_entities should transform cursor documents into Entity models."""

    collection = MagicMock()
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=[{"_id": ObjectId(), "name": "one", "entity_values": []}])
    collection.find.return_value = cursor

    result = await store.list_entities(collection)

    assert isinstance(result, list)
    assert all(isinstance(item, Entity) for item in result)
    collection.find.assert_called_once()
    cursor.to_list.assert_awaited_once_with(length=None)


@pytest.mark.asyncio
async def test_edit_entity_invokes_update() -> None:
    """edit_entity should issue an update_one call with the provided data."""

    collection = AsyncMock()
    entity_id = ObjectId()
    payload = {"name": "updated"}

    await store.edit_entity(collection, str(entity_id), payload)

    collection.update_one.assert_awaited_once_with(
        {"_id": entity_id}, {"$set": payload}
    )


@pytest.mark.asyncio
async def test_delete_entity_calls_delete_one() -> None:
    """delete_entity should remove the document matching the ObjectId."""

    collection = AsyncMock()
    entity_id = ObjectId()

    await store.delete_entity(collection, str(entity_id))

    collection.delete_one.assert_awaited_once_with({"_id": entity_id})


@pytest.mark.asyncio
async def test_list_synonyms_derives_mappings(monkeypatch) -> None:
    """list_synonyms should build synonym-to-canonical mappings from stored entities."""

    entity = Entity(
        name="decor",
        entity_values=[
            EntityValue(value="primary", synonyms=["alias-a", "alias-b"])
        ],
    )
    list_entities_mock = AsyncMock(return_value=[entity])
    monkeypatch.setattr(store, "list_entities", list_entities_mock)
    collection = AsyncMock()

    synonyms = await store.list_synonyms(collection)

    assert synonyms == {"alias-a": "primary", "alias-b": "primary"}
    list_entities_mock.assert_awaited_once_with(collection)


@pytest.mark.asyncio
async def test_bulk_import_entities_clears_store_when_empty() -> None:
    """bulk_import_entities should delete all documents when given an empty batch."""

    collection = AsyncMock()

    result = await store.bulk_import_entities(collection, [])

    assert result == []
    collection.delete_many.assert_awaited_once_with({})


@pytest.mark.asyncio
async def test_bulk_import_entities_upserts_named_entities(monkeypatch) -> None:
    """bulk_import_entities should upsert provided named entities and remove stale ones."""

    collection = AsyncMock()
    first_id = ObjectId()
    collection.update_one = AsyncMock(
        side_effect=[FakeUpdateResult(first_id), FakeUpdateResult(None)]
    )
    collection.delete_many = AsyncMock()

    batch = [
        {"name": "Alpha", "entity_values": []},
        {"name": "Beta", "entity_values": []},
    ]

    created = await store.bulk_import_entities(collection, batch)

    assert created == [str(first_id)]
    assert collection.update_one.await_count == 2
    collection.delete_many.assert_awaited_once_with(
        {"name": {"$nin": ["Alpha", "Beta"]}}
    )


@pytest.mark.asyncio
async def test_bulk_import_entities_skips_unnamed_documents() -> None:
    """Documents without a canonical name should be ignored and trigger full cleanup."""

    collection = AsyncMock()
    collection.update_one = AsyncMock()
    collection.delete_many = AsyncMock()

    result = await store.bulk_import_entities(collection, [{"synonyms": []}])

    assert result == []
    collection.update_one.assert_not_awaited()
    collection.delete_many.assert_awaited_once_with({})


@pytest.mark.asyncio
async def test_mongo_repository_delegates_methods(monkeypatch) -> None:
    """MongoEntityRepository should forward calls to the module-level helpers."""

    collection = AsyncMock()
    repo = store.MongoEntityRepository(collection)

    helpers = {
        "add_entity": AsyncMock(return_value="added"),
        "get_entity": AsyncMock(return_value="fetched"),
        "list_entities": AsyncMock(return_value="listed"),
        "edit_entity": AsyncMock(return_value=None),
        "delete_entity": AsyncMock(return_value=None),
        "list_synonyms": AsyncMock(return_value={"alias": "canon"}),
        "bulk_import_entities": AsyncMock(return_value=["created"]),
    }

    for name, mock in helpers.items():
        monkeypatch.setattr(store, name, mock)

    assert await repo.add_entity({"name": "X"}) == "added"
    helpers["add_entity"].assert_awaited_once_with(collection, {"name": "X"})

    assert await repo.get_entity("1") == "fetched"
    helpers["get_entity"].assert_awaited_once_with(collection, "1")

    assert await repo.list_entities() == "listed"
    helpers["list_entities"].assert_awaited_once_with(collection)

    await repo.edit_entity("1", {"name": "Y"})
    helpers["edit_entity"].assert_awaited_once_with(collection, "1", {"name": "Y"})

    await repo.delete_entity("1")
    helpers["delete_entity"].assert_awaited_once_with(collection, "1")

    assert await repo.list_synonyms() == {"alias": "canon"}
    helpers["list_synonyms"].assert_awaited_once_with(collection)

    assert await repo.bulk_import_entities([{"name": "Z"}]) == ["created"]
    helpers["bulk_import_entities"].assert_awaited_once_with(
        collection, [{"name": "Z"}]
    )