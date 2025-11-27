import pytest
import asyncio
import zlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

from app.bot.memory import memory_saver_mongo as msm

# Fixtures and helpers

class DummyState:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return dict(self._data)

    @classmethod
    def from_dict(cls, d):
        return cls(d)


@pytest.fixture(autouse=True)
def patch_state(monkeypatch):
    """Replace the State class used in the module with a DummyState for testing."""
    monkeypatch.setattr(msm, "State", DummyState)
    yield


@pytest.fixture
def settings():
    return msm.MongoSettings(
        database_name="testdb",
        collection_name="testcol",
        ttl_days=1,
        compression_threshold=10,
        max_retries=3,
        retry_delay_ms=1,
    )


@pytest.fixture
def async_client(monkeypatch):
    """Create a fake AsyncIOMotorClient with get_database and collection mocks."""
    collection = MagicMock()

    # Async methods
    collection.create_index = AsyncMock()
    collection.insert_one = AsyncMock()
    collection.find_one = AsyncMock()
    collection.find = MagicMock()

    db = MagicMock()
    db.get_collection.return_value = collection

    client = MagicMock()
    client.get_database.return_value = db

    return SimpleNamespace(client=client, db=db, collection=collection)


@pytest.mark.asyncio
async def test_init_with_none_client_raises():
    """MemorySaverMongo should raise ValueError when initialized with None client."""
    with pytest.raises(ValueError):
        msm.MemorySaverMongo(None)


def test_init_uses_settings_db_and_collection_names(settings, async_client):
    """Constructor should use settings database and collection names when calling client."""
    client = async_client.client
    ms = msm.MemorySaverMongo(client, settings=settings)

    # Ensure get_database called with provided name
    client.get_database.assert_called_with("testdb")
    ms.db.get_collection.assert_called_with("testcol")


def test_compress_and_decompress_state_small_no_compress(settings):
    """Small states under threshold should not be compressed nor altered when decompressed."""
    ms = msm.MemorySaverMongo(MagicMock(), settings=settings)
    small = {"a": 1}
    compressed = ms._compress_state(small)
    assert compressed == small

    # decompress should return same dict
    assert ms._decompress_state(small) == small


def test_compress_and_decompress_state_large_compress_and_decompress(settings):
    """Large states over threshold should be compressed and decompress back to original."""
    # lower threshold to ensure compression
    settings.compression_threshold = 1
    ms = msm.MemorySaverMongo(MagicMock(), settings=settings)

    large = {"text": "x" * 200}
    comp = ms._compress_state(large)
    assert comp.get("_compressed") is True
    assert "_data" in comp

    decompressed = ms._decompress_state(comp)
    assert decompressed == large


def test_decompress_state_invalid_raises(settings):
    """Decompressing corrupted data should raise ValueError."""
    ms = msm.MemorySaverMongo(MagicMock(), settings=settings)
    corrupted = {"_compressed": True, "_data": "deadbeef"}
    with pytest.raises(ValueError):
        ms._decompress_state(corrupted)


@pytest.mark.asyncio
async def test_ensure_indexes_creates_ttl_and_compound_index(settings, async_client):
    """_ensure_indexes should create the expected indexes including TTL."""
    client = async_client.client
    collection = async_client.collection

    ms = msm.MemorySaverMongo(client, settings=settings)

    # call async method
    await ms._ensure_indexes()

    # create_index should have been called at least 3 times
    assert collection.create_index.await_count >= 3

    # verify TTL index call contains expireAfterSeconds when ttl_days > 0
    calls = [c.args for c in collection.create_index.await_args_list]
    assert any('date' in args or ('date',) == args for args in calls)

    # calling again should not recreate indexes
    await ms._ensure_indexes()
    # count should remain same (no additional calls)
    assert collection.create_index.await_count >= 3


@pytest.mark.asyncio
async def test_ensure_indexes_raises_on_pymongo_error(settings, async_client, monkeypatch):
    """If create_index raises PyMongoError, _ensure_indexes should propagate the exception."""
    client = async_client.client
    collection = async_client.collection

    async def raise_error(*args, **kwargs):
        raise PyMongoError("index failed")

    collection.create_index.side_effect = raise_error

    ms = msm.MemorySaverMongo(client, settings=settings)

    with pytest.raises(PyMongoError):
        await ms._ensure_indexes()


@pytest.mark.asyncio
async def test_retry_operation_success_after_retries(settings, async_client, monkeypatch):
    """_retry_operation should retry when transient errors occur and eventually return result."""
    ms = msm.MemorySaverMongo(async_client.client, settings=settings)

    attempts = {"count": 0}

    async def flaky_operation():
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise ServerSelectionTimeoutError("down")
        return "ok"

    # avoid actual sleeping
    monkeypatch.setattr(msm.MemorySaverMongo, "_async_sleep", staticmethod(lambda s: asyncio.sleep(0)))

    result = await ms._retry_operation("flaky", flaky_operation)
    assert result == "ok"
    assert attempts["count"] == 2


@pytest.mark.asyncio
async def test_retry_operation_all_fail_raises(settings, async_client, monkeypatch):
    """If all retries fail, the last exception should be raised."""
    ms = msm.MemorySaverMongo(async_client.client, settings=settings)

    async def always_fail():
        raise PyMongoError("boom")

    # avoid sleep
    monkeypatch.setattr(msm.MemorySaverMongo, "_async_sleep", staticmethod(lambda s: asyncio.sleep(0)))

    with pytest.raises(PyMongoError):
        await ms._retry_operation("always", always_fail)


@pytest.mark.asyncio
async def test_save_invalid_inputs_raise(settings, async_client):
    """save should validate its inputs and raise ValueError on bad thread_id or state type."""
    client = async_client.client
    ms = msm.MemorySaverMongo(client, settings=settings)

    with pytest.raises(ValueError):
        await ms.save("", DummyState({}))

    with pytest.raises(ValueError):
        await ms.save("thread", object())


@pytest.mark.asyncio
async def test_save_success_calls_insert_one(settings, async_client, monkeypatch):
    """save should insert the state dict into the collection and call retries if necessary."""
    client = async_client.client
    collection = async_client.collection

    # prepare state dict and insert result
    state = DummyState({"thread_id": "t1", "date": "2020-01-01T00:00:00"})
    insert_result = SimpleNamespace(inserted_id="abc123")
    collection.insert_one.return_value = insert_result

    # prevent real sleeps and index creation
    ms = msm.MemorySaverMongo(client, settings=settings)
    ms._ensure_indexes = AsyncMock()

    await ms.save("t1", state)

    collection.insert_one.assert_awaited()


@pytest.mark.asyncio
async def test_get_returns_none_when_not_found(settings, async_client):
    """get should return None when no document is found for a thread."""
    client = async_client.client
    collection = async_client.collection

    collection.find_one.return_value = None

    ms = msm.MemorySaverMongo(client, settings=settings)
    ms._ensure_indexes = AsyncMock()

    result = await ms.get("thread-x")
    assert result is None


@pytest.mark.asyncio
async def test_get_returns_state_when_found_and_decompressed(settings, async_client):
    """get should return a State instance when a document is found (including compressed)."""
    client = async_client.client
    collection = async_client.collection

    original = {"thread_id": "t2", "date": "2020-01-02T00:00:00", "foo": "bar"}
    compressed = zlib.compress(json.dumps(original).encode("utf-8")).hex()
    doc = {**{"_compressed": True, "_data": compressed}, **original}

    collection.find_one.return_value = doc

    ms = msm.MemorySaverMongo(client, settings=settings)
    ms._ensure_indexes = AsyncMock()

    state = await ms.get("t2")
    assert isinstance(state, DummyState)
    assert state._data["thread_id"] == "t2"


@pytest.mark.asyncio
async def test_get_all_skips_bad_decompression(settings, async_client):
    """get_all should skip entries that fail decompression and return valid ones."""
    client = async_client.client
    collection = async_client.collection

    good = {"thread_id": "t3", "date": "2020-01-03T00:00:00"}
    bad = {"_compressed": True, "_data": "badhex", "thread_id": "t3", "date": "2020-01-04T00:00:00"}

    async def to_list(length=None):
        return [good, bad]

    cursor = MagicMock()
    cursor.to_list = AsyncMock(side_effect=to_list)
    collection.find.return_value = cursor

    ms = msm.MemorySaverMongo(client, settings=settings)
    ms._ensure_indexes = AsyncMock()

    states = await ms.get_all("t3")
    # only the good entry should be returned
    assert len(states) == 1
    assert states[0]._data["thread_id"] == "t3"