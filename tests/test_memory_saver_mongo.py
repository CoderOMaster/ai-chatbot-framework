from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Coroutine
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo.errors import PyMongoError

from app.bot.memory.memory_saver_mongo import (
    MemorySaverMongo,
    MemorySaverMongoError,
    _STATE_PROJECTION,
)
from app.bot.memory.models import State


@pytest.fixture(autouse=True)
def fake_app_config(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Provide a controlled app_config object so tests do not depend on external env vars."""

    config = SimpleNamespace(MONGODB_DATABASE="configured_db")
    monkeypatch.setattr(
        "app.bot.memory.memory_saver_mongo.app_config",
        config,
    )
    return config


@pytest.fixture
def example_state() -> State:
    """Create a minimal State instance for testing persistence helpers."""

    return State(thread_id="thread-123")


def test_init_uses_app_config_database_when_not_overridden() -> None:
    """Ensure default database configuration is used when no override is supplied."""

    client = MagicMock()
    db = MagicMock()
    collection = MagicMock()
    client.get_database.return_value = db
    db.get_collection.return_value = collection

    saver = MemorySaverMongo(client=client, timeout_seconds=1)

    client.get_database.assert_called_once_with("configured_db")
    db.get_collection.assert_called_once_with("state")
    assert saver._collection is collection


def test_init_raises_when_timeout_non_positive() -> None:
    """Verify that instantiating with a non-positive timeout fails fast."""

    with pytest.raises(ValueError):
        MemorySaverMongo(client=MagicMock(), timeout_seconds=0)


def test_default_collection_factory_constructs_collection() -> None:
    """The default factory should query the configured database and collection."""

    client = MagicMock()
    db = MagicMock()
    collection = MagicMock()
    client.get_database.return_value = db
    db.get_collection.return_value = collection

    saver = MemorySaverMongo(
        client=client,
        database_name="custom_db",
        collection_name="custom_coll",
        timeout_seconds=1,
    )

    client.get_database.assert_called_once_with("custom_db")
    db.get_collection.assert_called_once_with("custom_coll")
    assert saver._collection is collection


@pytest.mark.asyncio
async def test_execute_returns_coroutine_result() -> None:
    """The helper should return coroutine results when everything completes normally."""

    saver = MemorySaverMongo(
        client=MagicMock(),
        collection_factory=lambda _: MagicMock(),
        timeout_seconds=1,
    )

    async def sample_coroutine() -> str:
        return "ok"

    assert await saver._execute(sample_coroutine(), "op") == "ok"


@pytest.mark.asyncio
async def test_execute_wraps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeouts from asyncio.wait_for are converted into MemorySaverMongoError."""

    saver = MemorySaverMongo(
        client=MagicMock(),
        collection_factory=lambda _: MagicMock(),
        timeout_seconds=0.1,
    )

    async def sample() -> None:
        await asyncio.sleep(0.001)

    def fake_wait_for(_: Coroutine, __: float) -> None:
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    with pytest.raises(MemorySaverMongoError) as excinfo:
        await saver._execute(sample(), "timeout op")

    assert "timed out" in str(excinfo.value)


@pytest.mark.asyncio
async def test_execute_wraps_pymongo_error() -> None:
    """Errors originating in motor/pymongo should be wrapped for the caller."""

    saver = MemorySaverMongo(
        client=MagicMock(),
        collection_factory=lambda _: MagicMock(),
        timeout_seconds=1,
    )

    async def failing() -> None:
        raise PyMongoError("boom")

    with pytest.raises(MemorySaverMongoError) as excinfo:
        await saver._execute(failing(), "pymongo op")

    assert "failed" in str(excinfo.value)


@pytest.mark.asyncio
async def test_save_invokes_insert_one_and_uses_execute(example_state: State) -> None:
    """Saving a state should call insert_one with the serialized payload."""

    collection = MagicMock()
    collection.insert_one = AsyncMock()
    saver = MemorySaverMongo(
        client=MagicMock(),
        collection_factory=lambda _: collection,
        timeout_seconds=1,
    )
    saver._execute = AsyncMock()

    await saver.save("thread-123", example_state)

    collection.insert_one.assert_called_once_with(example_state.to_dict())
    saver._execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_returns_state_when_document_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """get() should rehydrate a State when Mongo returns a document."""

    document = {"thread_id": "thread-1"}
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=document)

    saver = MemorySaverMongo(
        client=MagicMock(),
        collection_factory=lambda _: collection,
        timeout_seconds=1,
    )
    saver._execute = AsyncMock(return_value=document)

    state_instance = State(thread_id="thread-1")
    monkeypatch.setattr(State, "from_dict", MagicMock(return_value=state_instance))

    result = await saver.get("thread-1")

    collection.find_one.assert_called_once_with(
        {"thread_id": "thread-1"},
        _STATE_PROJECTION,
        sort=[("$natural", -1)],
    )
    State.from_dict.assert_called_once_with(document)
    assert result is state_instance


@pytest.mark.asyncio
async def test_get_returns_none_when_no_document() -> None:
    """get() should return None when Mongo yields no data."""

    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=None)

    saver = MemorySaverMongo(
        client=MagicMock(),
        collection_factory=lambda _: collection,
        timeout_seconds=1,
    )
    saver._execute = AsyncMock(return_value=None)

    result = await saver.get("thread-1")

    assert result is None


@pytest.mark.asyncio
async def test_get_all_returns_historical_states(monkeypatch: pytest.MonkeyPatch) -> None:
    """All returned documents should be transformed into State instances."""

    documents = [
        {"thread_id": "thread-1", "value": 1},
        {"thread_id": "thread-1", "value": 2},
    ]
    collection = MagicMock()
    find_result = MagicMock()
    find_result.to_list = AsyncMock(return_value=documents)
    collection.find = MagicMock(return_value=find_result)

    saver = MemorySaverMongo(
        client=MagicMock(),
        collection_factory=lambda _: collection,
        timeout_seconds=1,
    )
    saver._execute = AsyncMock(return_value=documents)

    monkeypatch.setattr(State, "from_dict", MagicMock(side_effect=lambda doc: f"state-{doc['value']}"))

    result = await saver.get_all("thread-1")

    collection.find.assert_called_once_with({"thread_id": "thread-1"}, sort=[("$natural", -1)])
    assert result == ["state-1", "state-2"]
    assert State.from_dict.call_count == len(documents)


@pytest.mark.asyncio
async def test_get_all_returns_empty_list_when_no_history() -> None:
    """An empty history should return an empty list instead of None."""

    collection = MagicMock()
    collection.find = MagicMock()

    saver = MemorySaverMongo(
        client=MagicMock(),
        collection_factory=lambda _: collection,
        timeout_seconds=1,
    )
    saver._execute = AsyncMock(return_value=[])

    result = await saver.get_all("thread-1")

    assert result == []