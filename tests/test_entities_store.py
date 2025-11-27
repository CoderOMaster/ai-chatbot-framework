import pytest
from unittest.mock import AsyncMock, MagicMock
from bson import ObjectId

import app.admin.entities.store as store

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def patch_collections(monkeypatch):
    """Patch entity_collection and audit_collection with mocks for all tests."""
    entity_col = MagicMock()
    audit_col = MagicMock()

    # Async methods
    entity_col.create_index = AsyncMock()
    entity_col.insert_one = AsyncMock()
    entity_col.find_one = AsyncMock()
    entity_col.count_documents = AsyncMock()
    # find will be set per-test when needed to capture the query
    entity_col.update_one = AsyncMock()
    entity_col.bulk_write = AsyncMock()

    audit_col.insert_one = AsyncMock()
    audit_col.find = MagicMock()

    monkeypatch.setattr(store, "entity_collection", entity_col)
    monkeypatch.setattr(store, "audit_collection", audit_col)

    # Make Entity.model_validate simply return the raw dict for easier assertions
    monkeypatch.setattr(store.Entity, "model_validate", staticmethod(lambda x: x))

    yield


# Validation tests
async def test_validate_entity_success():
    """_validate_entity_data accepts valid payloads without raising."""
    data = {"name": "Test", "entity_values": [{"value": "v1"}]}
    await store._validate_entity_data(data)


@pytest.mark.parametrize("bad_data, expected_msg", [
    ({}, "Entity name is required"),
    ({"name": "x" * 256}, "Entity name must not exceed 255 characters"),
    ({"name": "A", "entity_values": "notalist"}, "entity_values must be a list"),
    ({"name": "A", "entity_values": ["notadict"]}, "entity_values[0] must be a dictionary"),
    ({"name": "A", "entity_values": [{}]}, "entity_values[0].value is required"),
])
async def test_validate_entity_errors(bad_data, expected_msg):
    """_validate_entity_data raises ValueError on invalid input."""
    with pytest.raises(ValueError) as exc:
        await store._validate_entity_data(bad_data)
    assert expected_msg in str(exc.value)


# Index creation
async def test_ensure_indexes_calls_create():
    """_ensure_indexes should call create_index on the collection for multiple fields."""
    # entity_collection.create_index is AsyncMock from fixture
    await store._ensure_indexes()
    assert store.entity_collection.create_index.await_count >= 1


# add_entity and get_entity
async def test_add_and_get_entity_success():
    """add_entity should insert, log audit, and return the created entity via get_entity."""
    sample = {"name": "E1", "entity_values": [{"value": "v"}]}

    # Simulate insert_one returning inserted_id
    fake_id = ObjectId()
    # insert_one returns a result object with inserted_id attribute
    ins_result = MagicMock()
    ins_result.inserted_id = fake_id
    store.entity_collection.insert_one.return_value = AsyncMock(return_value=ins_result)()

    # find_one should return document when get_entity is called
    returned = {"_id": fake_id, "name": "E1", "entity_values": [{"value": "v"}], "is_deleted": False}
    store.entity_collection.find_one.return_value = returned

    result = await store.add_entity(sample, user_id="user1")

    # Should return the validated entity (we patched model_validate to return dict)
    assert result["_id"] == fake_id
    store.audit_collection.insert_one.assert_awaited()
    store.entity_collection.insert_one.assert_awaited()


async def test_get_entity_not_found():
    """get_entity raises when the entity does not exist or is deleted."""
    store.entity_collection.find_one.return_value = None
    with pytest.raises(ValueError):
        await store.get_entity(str(ObjectId()))


# list_entities validations and paging
async def test_list_entities_invalid_params():
    """Invalid pagination and sort parameters raise ValueError."""
    with pytest.raises(ValueError):
        await store.list_entities(page_size=0)
    with pytest.raises(ValueError):
        await store.list_entities(page=0)
    with pytest.raises(ValueError):
        await store.list_entities(sort_by="bad_field")
    with pytest.raises(ValueError):
        await store.list_entities(sort_order="sideways")


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs
        self.query = None

    def sort(self, *args, **kwargs):
        return self

    def skip(self, _):
        return self

    def limit(self, _):
        return self

    async def to_list(self):
        return self._docs


async def test_list_entities_success():
    """list_entities returns paginated entities and total count using the query and sort/drop in place."""
    docs = [
        {"_id": ObjectId(), "name": "A", "entity_values": [], "is_deleted": False},
        {"_id": ObjectId(), "name": "B", "entity_values": [], "is_deleted": False},
    ]

    # count_documents returns total
    store.entity_collection.count_documents.return_value = 2

    # find should return a cursor-like object
    def fake_find(query):
        # attach last_query for assertions
        fake = FakeCursor(docs)
        fake.query = query
        return fake

    store.entity_collection.find.side_effect = fake_find

    entities, total = await store.list_entities(page=1, page_size=2, sort_by="created_at", sort_order="asc")

    assert total == 2
    assert len(entities) == 2

    # Test name filter applies regex query
    def fake_find_filter(query):
        assert "name" in query and "$regex" in query["name"]
        return FakeCursor(docs)

    store.entity_collection.find.side_effect = fake_find_filter
    await store.list_entities(name_filter="search")


# edit_entity
async def test_edit_entity_not_found():
    """edit_entity raises when entity not exists."""
    store.entity_collection.find_one.return_value = None
    with pytest.raises(ValueError):
        await store.edit_entity(str(ObjectId()), {"name": "X"})


async def test_edit_entity_success():
    """edit_entity updates and returns the updated entity."""
    ent_id = ObjectId()
    existing = {"_id": ent_id, "name": "Old", "entity_values": [{"value": "v"}], "is_deleted": False}
    # find_one should first return existing then later return updated when get_entity called
    store.entity_collection.find_one.side_effect = [existing, {"_id": ent_id, "name": "New", "entity_values": [{"value": "v"}], "is_deleted": False}]

    # update_one doesn't need to return anything
    store.entity_collection.update_one.return_value = AsyncMock()

    res = await store.edit_entity(str(ent_id), {"name": "New"}, user_id="u1")
    assert res["name"] == "New"
    store.audit_collection.insert_one.assert_awaited()
    store.entity_collection.update_one.assert_awaited()


# delete and restore
async def test_delete_entity_not_found():
    """delete_entity should raise when entity missing or already deleted."""
    store.entity_collection.find_one.return_value = None
    with pytest.raises(ValueError):
        await store.delete_entity(str(ObjectId()))


async def test_delete_entity_success():
    """delete_entity marks the entity as deleted and logs audit."""
    ent_id = ObjectId()
    existing = {"_id": ent_id, "name": "X", "is_deleted": False}
    store.entity_collection.find_one.return_value = existing
    store.entity_collection.update_one.return_value = AsyncMock()

    await store.delete_entity(str(ent_id), user_id="u2")

    # Ensure update_one was called to set is_deleted True
    assert store.entity_collection.update_one.await_count == 1
    store.audit_collection.insert_one.assert_awaited()


async def test_restore_entity_errors_and_success():
    """restore_entity raises for missing/not-deleted and succeeds for deleted entities."""
    ent_id = ObjectId()

    # missing
    store.entity_collection.find_one.return_value = None
    with pytest.raises(ValueError):
        await store.restore_entity(str(ent_id))

    # not deleted
    store.entity_collection.find_one.return_value = {"_id": ent_id, "is_deleted": False}
    with pytest.raises(ValueError):
        await store.restore_entity(str(ent_id))

    # successful restore: sequence of find_one calls: check existence -> then get_entity returns restored
    store.entity_collection.find_one.side_effect = [
        {"_id": ent_id, "is_deleted": True},  # existence check
        {"_id": ent_id, "is_deleted": False, "name": "Z"},  # get_entity
    ]
    store.entity_collection.update_one.return_value = AsyncMock()

    res = await store.restore_entity(str(ent_id), user_id="u3")
    assert res["name"] == "Z"
    store.audit_collection.insert_one.assert_awaited()


# list_synonyms
async def test_list_synonyms(monkeypatch):
    """list_synonyms aggregates synonyms from returned entities."""

    class Val:
        def __init__(self, value, synonyms):
            self.value = value
            self.synonyms = synonyms

    class E:
        def __init__(self, vals):
            self.entity_values = vals

    async def fake_list_entities(page=1, page_size=50, skip=None, sort_by="created_at", sort_order="desc", name_filter=None):
        return [E([Val("v1", ["s1", "s2"]), Val("v2", ["s3"])])], 1

    monkeypatch.setattr(store, "list_entities", fake_list_entities)

    syn = await store.list_synonyms()
    assert syn["s1"] == "v1"
    assert syn["s3"] == "v2"


# bulk_import_entities
async def test_bulk_import_empty_returns_empty():
    """bulk_import_entities should return empty list when given no entities."""
    res = await store.bulk_import_entities([])
    assert res == []


async def test_bulk_import_validation_failure(monkeypatch):
    """If validation fails for any entity, bulk_import raises ValueError."""
    # Patch _validate_entity_data to raise for a particular entity
    async def fail_validate(data):
        raise ValueError("bad")

    monkeypatch.setattr(store, "_validate_entity_data", fail_validate)

    with pytest.raises(ValueError):
        await store.bulk_import_entities([{"name": "A", "entity_values": [{"value": "v"}]}])


async def test_bulk_import_success(monkeypatch):
    """bulk_import_entities should perform bulk_write and return created IDs when upserts occur."""
    # restore validate
    monkeypatch.setattr(store, "_validate_entity_data", AsyncMock())

    # Fake result from bulk_write
    class Res:
        def __init__(self):
            # upserted_ids is a dict mapping index->ObjectId
            self.upserted_ids = {0: ObjectId(), 1: ObjectId()}
            self.modified_count = 1
            self.upserted_count = 2

    store.entity_collection.bulk_write.return_value = Res()

    # Patch _log_audit to avoid real DB calls
    monkeypatch.setattr(store, "_log_audit", AsyncMock())

    entities = [
        {"name": "A", "entity_values": [{"value": "v1"}]},
        {"name": "B", "entity_values": [{"value": "v2"}]},
    ]

    created = await store.bulk_import_entities(entities, user_id="u4")
    assert isinstance(created, list)
    assert len(created) == 2
    store.entity_collection.bulk_write.assert_awaited()
    store._log_audit.assert_awaited()


# get_audit_log
async def test_get_audit_log_filters_and_returns():
    """get_audit_log should convert entity_id to ObjectId and return audit entries."""
    # Prepare fake cursor
    entries = [{"action": "create"}, {"action": "update"}]

    class FakeAuditCursor:
        def sort(self, *args, **kwargs):
            return self

        def limit(self, _):
            return self

        async def to_list(self):
            return entries

    def fake_find(query):
        # If entity_id provided it should be an ObjectId
        if "entity_id" in query:
            assert isinstance(query["entity_id"], ObjectId)
        return FakeAuditCursor()

    store.audit_collection.find.side_effect = fake_find

    res = await store.get_audit_log(entity_id=str(ObjectId()), action="create", limit=10)
    assert res == entries


# ensure _log_audit swallows exceptions (does not raise)
async def test_log_audit_exception_handling():
    """_log_audit should catch and log exceptions from insert_one instead of raising."""
    # Make insert_one raise
    async def raise_insert(doc):
        raise RuntimeError("db down")

    store.audit_collection.insert_one.side_effect = raise_insert

    # Should not raise
    await store._log_audit(str(ObjectId()), "create", {"k": "v"})