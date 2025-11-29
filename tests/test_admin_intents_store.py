import pytest
from bson import ObjectId
from bson.errors import InvalidId
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from motor.motor_asyncio import AsyncIOMotorCollection

from app.admin.intents import store
from app.admin.intents.schemas import Intent


INTENT_BASE_DATA = {
    "_id": ObjectId(),
    "name": "booking",
    "userDefined": True,
    "intentId": "booking_intent",
    "apiTrigger": False,
    "speechResponse": "Test response",
    "parameters": [],
    "labeledSentences": [],
    "trainingData": [],
}


@pytest.fixture
def mock_collection() -> AsyncMock:
    """Return a mocked AsyncIOMotorCollection with asynchronous helpers."""
    collection = AsyncMock(spec=AsyncIOMotorCollection)
    collection.find_one = AsyncMock()
    collection.find = Mock()
    collection.update_one = AsyncMock()
    collection.delete_one = AsyncMock()
    return collection


@pytest.mark.asyncio
async def test_add_intent_success(monkeypatch: pytest.MonkeyPatch, mock_collection: AsyncMock) -> None:
    """Validate add_intent inserts and returns the stored Intent."""
    inserted_id = ObjectId()
    # Make insert_one return an awaitable that resolves to SimpleNamespace
    mock_collection.insert_one = AsyncMock(return_value=SimpleNamespace(inserted_id=inserted_id))
    expected_intent = Intent.model_validate(INTENT_BASE_DATA)
    get_intent_mock = AsyncMock(return_value=expected_intent)
    monkeypatch.setattr(store, "get_intent", get_intent_mock)

    result = await store.add_intent(mock_collection, {"name": "booking"})

    assert result == expected_intent
    get_intent_mock.assert_awaited_once_with(mock_collection, str(inserted_id))
    mock_collection.insert_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_intent_success(mock_collection: AsyncMock) -> None:
    """Ensure get_intent converts the Mongo document to an Intent model."""
    document = INTENT_BASE_DATA.copy()
    document["_id"] = ObjectId()
    mock_collection.find_one.return_value = document

    result = await store.get_intent(mock_collection, str(document["_id"]))

    assert isinstance(result, Intent)
    assert result.name == document["name"]
    mock_collection.find_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_intent_invalid_id_raises(mock_collection: AsyncMock) -> None:
    """Passing a non-ObjectId string should raise InvalidId from bson."""
    with pytest.raises(InvalidId):  # ObjectId validation occurs prior to DB call
        await store.get_intent(mock_collection, "invalid-id")


@pytest.mark.asyncio
async def test_list_intents_returns_models(mock_collection: AsyncMock) -> None:
    """List intents should return Intent instances for every document."""
    cursor = AsyncMock()
    documents = [INTENT_BASE_DATA.copy(), INTENT_BASE_DATA.copy()]
    cursor.to_list = AsyncMock(return_value=documents)
    mock_collection.find.return_value = cursor

    result = await store.list_intents(mock_collection)

    assert len(result) == len(documents)
    assert all(isinstance(intent, Intent) for intent in result)
    cursor.to_list.assert_awaited_once_with(length=None)


@pytest.mark.asyncio
async def test_edit_intent_updates_document(mock_collection: AsyncMock) -> None:
    """Edit intent should call update_one with the provided payload."""
    intent_id = str(ObjectId())
    payload = {"speechResponse": "updated"}

    await store.edit_intent(mock_collection, intent_id, payload)

    assert mock_collection.update_one.await_count == 1
    args, kwargs = mock_collection.update_one.call_args
    assert args[0]["_id"] == ObjectId(intent_id)
    assert args[1] == {"$set": payload}


@pytest.mark.asyncio
async def test_delete_intent_removes_document(mock_collection: AsyncMock) -> None:
    """Deleting an intent should forward ObjectId based filter."""
    intent_id = str(ObjectId())

    await store.delete_intent(mock_collection, intent_id)

    mock_collection.delete_one.assert_awaited_once()
    assert mock_collection.delete_one.call_args.args[0]["_id"] == ObjectId(intent_id)


@pytest.mark.asyncio
async def test_bulk_import_intents_creates_new_ids(mock_collection: AsyncMock) -> None:
    """Bulk import should return identifiers for newly created intents only."""
    first_id = ObjectId()
    second_id = None
    mock_collection.update_one.side_effect = [
        SimpleNamespace(upserted_id=first_id),
        SimpleNamespace(upserted_id=second_id),
    ]
    payloads = [{"name": "booking"}, {"name": "cancellation"}]

    result = await store.bulk_import_intents(mock_collection, payloads)

    assert result == [str(first_id)]
    assert mock_collection.update_one.call_count == len(payloads)


@pytest.mark.asyncio
async def test_bulk_import_intents_empty_list(mock_collection: AsyncMock) -> None:
    """No updates should be executed when the payload list is empty."""
    result = await store.bulk_import_intents(mock_collection, [])

    assert result == []
    mock_collection.update_one.assert_not_awaited()


def _setup_repository(collection: AsyncMock) -> store.MongoIntentRepository:
    """Helper fixture to instantiate MongoIntentRepository."""
    return store.MongoIntentRepository(collection)


def _intent_data() -> dict:
    data = INTENT_BASE_DATA.copy()
    data["_id"] = ObjectId()
    return data


@pytest.mark.asyncio
async def test_mongo_repository_add_intent_delegates(monkeypatch: pytest.MonkeyPatch, mock_collection: AsyncMock) -> None:
    """Repository add_intent should call the module level helper."""
    repo = _setup_repository(mock_collection)
    expected_intent = Intent.model_validate(_intent_data())
    helper = AsyncMock(return_value=expected_intent)
    monkeypatch.setattr(store, "add_intent", helper)

    result = await repo.add_intent({"name": "booking"})

    assert result == expected_intent
    helper.assert_awaited_once_with(mock_collection, {"name": "booking"})


@pytest.mark.asyncio
async def test_mongo_repository_get_intent_delegates(monkeypatch: pytest.MonkeyPatch, mock_collection: AsyncMock) -> None:
    """Repository get_intent should delegate to the store helper."""
    repo = _setup_repository(mock_collection)
    helper = AsyncMock(return_value=Intent.model_validate(_intent_data()))
    monkeypatch.setattr(store, "get_intent", helper)

    await repo.get_intent("test-id")

    helper.assert_awaited_once_with(mock_collection, "test-id")


@pytest.mark.asyncio
async def test_mongo_repository_list_intents_delegates(monkeypatch: pytest.MonkeyPatch, mock_collection: AsyncMock) -> None:
    """Ensure list_intents proxies to the shared helper."""
    repo = _setup_repository(mock_collection)
    helper = AsyncMock(return_value=[Intent.model_validate(_intent_data())])
    monkeypatch.setattr(store, "list_intents", helper)

    await repo.list_intents()

    helper.assert_awaited_once_with(mock_collection)


@pytest.mark.asyncio
async def test_mongo_repository_edit_intent_delegates(monkeypatch: pytest.MonkeyPatch, mock_collection: AsyncMock) -> None:
    """Edit operations should route through the module helper."""
    repo = _setup_repository(mock_collection)
    helper = AsyncMock()
    monkeypatch.setattr(store, "edit_intent", helper)

    await repo.edit_intent("test-id", {"speechResponse": "ok"})

    helper.assert_awaited_once_with(mock_collection, "test-id", {"speechResponse": "ok"})


@pytest.mark.asyncio
async def test_mongo_repository_delete_intent_delegates(monkeypatch: pytest.MonkeyPatch, mock_collection: AsyncMock) -> None:
    """Delete should reuse the shared helper."""
    repo = _setup_repository(mock_collection)
    helper = AsyncMock()
    monkeypatch.setattr(store, "delete_intent", helper)

    await repo.delete_intent("test-id")

    helper.assert_awaited_once_with(mock_collection, "test-id")


@pytest.mark.asyncio
async def test_mongo_repository_bulk_import_delegates(monkeypatch: pytest.MonkeyPatch, mock_collection: AsyncMock) -> None:
    """Bulk import should call the helper and forward return values."""
    repo = _setup_repository(mock_collection)
    helper = AsyncMock(return_value=["id-1", "id-2"])
    monkeypatch.setattr(store, "bulk_import_intents", helper)

    result = await repo.bulk_import_intents([{"name": "booking"}])

    assert result == ["id-1", "id-2"]
    helper.assert_awaited_once_with(mock_collection, [{"name": "booking"}])


__all__ = ["test_add_intent_success"]  # noqa: F401 to silence unused export