import pytest
import asyncio
from types import SimpleNamespace
from bson import ObjectId

import app.admin.intents.store as store

pytestmark = pytest.mark.asyncio


class AsyncCursor:
    def __init__(self, items):
        self._items = items

    def skip(self, _):
        return self

    def limit(self, _):
        return self

    def sort(self, *_, **__):
        return self

    async def to_list(self):
        return self._items


class DummyResult:
    def __init__(self, inserted_id=None, matched_count=0, modified_count=0, deleted_count=0, upserted_id=None):
        self.inserted_id = inserted_id
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.deleted_count = deleted_count
        self.upserted_id = upserted_id


@pytest.fixture(autouse=True)
def patch_intent_model(monkeypatch):
    """Patch Intent.model_validate to return a simple object with expected interface."""
    def model_validate(data):
        # Return an object that has attributes and model_dump method used in code
        obj = SimpleNamespace(**data)

        def model_dump():
            return data

        obj.model_dump = model_dump
        return obj

    monkeypatch.setattr(store, "Intent", SimpleNamespace(model_validate=model_validate))
    yield


@pytest.fixture
def reset_collections(monkeypatch):
    """Ensure the module-level collections can be replaced per test."""
    monkeypatch.setattr(store, "intent_collection", SimpleNamespace())
    monkeypatch.setattr(store, "intent_history_collection", SimpleNamespace())
    yield


async def test_validate_intent_missing_fields():
    """_validate_intent_data should raise when required fields are missing."""
    with pytest.raises(store.IntentValidationError):
        await store._validate_intent_data({})


async def test_validate_intent_invalid_types():
    """_validate_intent_data should raise for empty strings and wrong parameter types."""
    data = {"name": " ", "intentId": "id", "speechResponse": "resp"}
    with pytest.raises(store.IntentValidationError):
        await store._validate_intent_data(data)

    data = {"name": "name", "intentId": "id", "speechResponse": " "}
    with pytest.raises(store.IntentValidationError):
        await store._validate_intent_data(data)

    data = {"name": "name", "intentId": "id", "speechResponse": "resp", "parameters": "not-a-list"}
    with pytest.raises(store.IntentValidationError):
        await store._validate_intent_data(data)


async def test_add_intent_success(monkeypatch, reset_collections):
    """add_intent should insert a document, create a version and return the stored Intent."""
    # Prepare fake insert_one result
    fake_id = ObjectId()
    async def fake_insert_one(doc):
        return DummyResult(inserted_id=fake_id)

    async def fake_history_insert(doc):
        return DummyResult(inserted_id=ObjectId())

    # find_one should return the stored document
    async def fake_find_one(query):
        return {"_id": fake_id, "name": "test", "intentId": "i1", "speechResponse": "r"}

    store.intent_collection.insert_one = fake_insert_one
    store.intent_collection.find_one = fake_find_one
    store.intent_history_collection.insert_one = fake_history_insert

    data = {"name": "test", "intentId": "i1", "speechResponse": "r"}
    intent = await store.add_intent(data)
    assert hasattr(intent, "name") and intent.name == "test"


async def test_get_intent_invalid_id():
    """get_intent should raise IntentNotFoundError for invalid ObjectId format."""
    with pytest.raises(store.IntentNotFoundError):
        await store.get_intent("not-a-valid-objectid")


async def test_get_intent_not_found(monkeypatch, reset_collections):
    """get_intent should raise when no document is found for a valid ObjectId."""
    valid_id = str(ObjectId())

    async def fake_find_one(query):
        return None

    store.intent_collection.find_one = fake_find_one
    with pytest.raises(store.IntentNotFoundError):
        await store.get_intent(valid_id)


async def test_list_intents_search_and_filters(monkeypatch, reset_collections):
    """list_intents should build query for search and filters and return validated objects and count."""
    docs = [
        {"_id": ObjectId(), "name": "Alpha", "intentId": "a1", "speechResponse": "r"},
        {"_id": ObjectId(), "name": "Beta", "intentId": "b1", "speechResponse": "r"},
    ]

    async def fake_count_documents(query):
        return len(docs)

    def fake_find(query):
        return AsyncCursor(docs)

    store.intent_collection.count_documents = fake_count_documents
    store.intent_collection.find = fake_find

    results, total = await store.list_intents(search="a", filters={"userDefined": True})
    assert total == 2
    assert isinstance(results, list)


async def test_edit_intent_success(monkeypatch, reset_collections):
    """edit_intent should validate, update and return the updated intent."""
    intent_id = str(ObjectId())

    # Patch get_intent to return an existing object with version
    async def fake_get_intent(_id):
        obj = SimpleNamespace(name="x", version=1, model_dump=lambda: {"name": "x"})
        return obj

    monkeypatch.setattr(store, "get_intent", fake_get_intent)

    async def fake_update_one(query, update):
        return DummyResult(matched_count=1, modified_count=1)

    async def fake_create_version(a, b, c):
        return str(ObjectId())

    store.intent_collection.update_one = fake_update_one
    monkeypatch.setattr(store, "_create_version", fake_create_version)

    # Final get_intent after update
    async def fake_get_intent_after(_id):
        return SimpleNamespace(name="updated", version=2, model_dump=lambda: {"name": "updated"})

    monkeypatch.setattr(store, "get_intent", fake_get_intent_after)

    updated = await store.edit_intent(intent_id, {"name": "updated", "intentId": "i", "speechResponse": "r"})
    assert updated.name == "updated"


async def test_edit_intent_not_found(monkeypatch, reset_collections):
    """edit_intent should raise if update matched_count is zero."""
    intent_id = str(ObjectId())

    async def fake_get_intent(_id):
        return SimpleNamespace(name="x", version=1, model_dump=lambda: {"name": "x"})

    monkeypatch.setattr(store, "get_intent", fake_get_intent)

    async def fake_update_one(query, update):
        return DummyResult(matched_count=0)

    store.intent_collection.update_one = fake_update_one

    with pytest.raises(store.IntentNotFoundError):
        await store.edit_intent(intent_id, {"name": "updated", "intentId": "i", "speechResponse": "r"})


async def test_delete_intent_success(monkeypatch, reset_collections):
    """delete_intent should remove the document and create a delete version record."""
    intent_id = str(ObjectId())

    async def fake_get_intent(_id):
        return SimpleNamespace(name="to_delete", model_dump=lambda: {"name": "to_delete"})

    monkeypatch.setattr(store, "get_intent", fake_get_intent)

    async def fake_delete_one(query):
        return DummyResult(deleted_count=1)

    async def fake_create_version(a, b, c):
        return str(ObjectId())

    store.intent_collection.delete_one = fake_delete_one
    monkeypatch.setattr(store, "_create_version", fake_create_version)

    # Should not raise
    await store.delete_intent(intent_id)


async def test_delete_intent_not_found(monkeypatch, reset_collections):
    """delete_intent should raise if nothing was deleted."""
    intent_id = str(ObjectId())

    async def fake_get_intent(_id):
        return SimpleNamespace(name="to_delete", model_dump=lambda: {"name": "to_delete"})

    monkeypatch.setattr(store, "get_intent", fake_get_intent)

    async def fake_delete_one(query):
        return DummyResult(deleted_count=0)

    store.intent_collection.delete_one = fake_delete_one

    with pytest.raises(store.IntentNotFoundError):
        await store.delete_intent(intent_id)


async def test_bulk_import_intents_empty(monkeypatch, reset_collections):
    """bulk_import_intents should return empty stats for empty input."""
    res = await store.bulk_import_intents([])
    assert res["total"] == 0
    assert res["created"] == []


async def test_bulk_import_intents_create_update_fail(monkeypatch, reset_collections):
    """bulk_import_intents should classify created, updated and failed intents with batching."""
    intents = [
        {"name": "create_me", "intentId": "c1", "speechResponse": "r"},
        {"name": "update_me", "intentId": "u1", "speechResponse": "r"},
        {"name": "bad", "intentId": "b1"},  # missing speechResponse should fail
    ]

    # First call: upserted -> created
    # Second call: modified_count -> updated
    async def fake_update_one_create(filter_q, update_q, upsert=False):
        return DummyResult(upserted_id=ObjectId())

    async def fake_update_one_update(filter_q, update_q, upsert=False):
        return DummyResult(modified_count=1)

    # We'll return different results based on passed name
    async def fake_update_one_combined(filter_q, update_q, upsert=False):
        name = update_q["$set"].get("name")
        if name == "create_me":
            return DummyResult(upserted_id=ObjectId())
        elif name == "update_me":
            return DummyResult(modified_count=1)
        else:
            return DummyResult()

    store.intent_collection.update_one = fake_update_one_combined
    monkeypatch.setattr(store, "_create_version", lambda a, b, c: asyncio.sleep(0))

    res = await store.bulk_import_intents(intents, batch_size=2)
    assert res["total"] == 3
    assert len(res["created"]) == 1
    assert len(res["updated"]) == 1
    assert len(res["failed"]) == 1


async def test_get_intent_history(monkeypatch, reset_collections):
    """get_intent_history should return a list of history records."""
    hid = str(ObjectId())
    history_docs = [{"version_number": 1, "data": {"name": "a"}}]

    def fake_find(query):
        return AsyncCursor(history_docs)

    store.intent_history_collection.find = fake_find

    res = await store.get_intent_history(hid)
    assert isinstance(res, list)
    assert res[0]["version_number"] == 1


async def test_rollback_intent_success(monkeypatch, reset_collections):
    """rollback_intent should restore data from history and create a rollback version."""
    intent_id = str(ObjectId())
    version_record = {"version_number": 1, "data": {"name": "restored", "intentId": "r1", "speechResponse": "r"}}

    async def fake_find_one(query):
        return version_record

    async def fake_update_one(query, update):
        return DummyResult(matched_count=1)

    async def fake_create_version(a, b, c):
        return str(ObjectId())

    async def fake_get_intent(_id):
        return SimpleNamespace(name="restored", version=1)

    store.intent_history_collection.find_one = fake_find_one
    store.intent_collection.update_one = fake_update_one
    monkeypatch.setattr(store, "_create_version", fake_create_version)
    monkeypatch.setattr(store, "get_intent", fake_get_intent)

    res = await store.rollback_intent(intent_id, 1)
    assert res.name == "restored"


async def test_rollback_intent_version_not_found(monkeypatch, reset_collections):
    """rollback_intent should raise IntentVersionError when version record absent."""
    intent_id = str(ObjectId())

    async def fake_find_one(query):
        return None

    store.intent_history_collection.find_one = fake_find_one

    with pytest.raises(store.IntentVersionError):
        await store.rollback_intent(intent_id, 99)


async def test_search_intents(monkeypatch, reset_collections):
    """search_intents should perform a regex search across provided fields and return validated intents."""
    docs = [{"_id": ObjectId(), "name": "Finder", "intentId": "f1", "speechResponse": "r"}]

    def fake_find(query):
        return AsyncCursor(docs)

    store.intent_collection.find = fake_find

    res = await store.search_intents("find")
    assert len(res) == 1
    assert res[0].name == "Finder"


async def test_filter_intents(monkeypatch, reset_collections):
    """filter_intents should translate filters to query and return results with count."""
    docs = [{"_id": ObjectId(), "name": "F", "intentId": "f1", "speechResponse": "r"}]

    async def fake_count_documents(query):
        return 1

    def fake_find(query):
        return AsyncCursor(docs)

    store.intent_collection.count_documents = fake_count_documents
    store.intent_collection.find = fake_find

    res, total = await store.filter_intents({"user_defined": True})
    assert total == 1
    assert res[0].name == "F"