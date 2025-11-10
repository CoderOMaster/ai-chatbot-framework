import pytest
from unittest.mock import AsyncMock

from app.bot.memory.memory_saver_mongo import MemorySaverMongo
from app.bot.memory.models import State
from app.bot.dialogue_manager.models import UserMessage


@pytest.mark.asyncio
async def test_save_inserts_state_document():
    mock_db = AsyncMock()
    mock_collection = AsyncMock()
    mock_db.get_collection.return_value = mock_collection

    saver = MemorySaverMongo(mock_db)

    state = State(thread_id="t1", user_message=UserMessage("t1", "hi", {}))
    await saver.save("t1", state)

    mock_collection.insert_one.assert_awaited_once()
    awaited = mock_collection.insert_one.await_args
    doc = awaited.args[0]
    assert doc["thread_id"] == "t1"
    assert doc["user_message"]["text"] == "hi"


@pytest.mark.asyncio
async def test_get_returns_most_recent_state_excluding_heavy_fields():
    mock_db = AsyncMock()
    mock_collection = AsyncMock()
    mock_db.get_collection.return_value = mock_collection

    saver = MemorySaverMongo(mock_db)

    stored = State(thread_id="t1")
    # what Mongo returns after projection
    mongo_doc = stored.to_dict().copy()
    # emulate excluded fields per implementation
    mongo_doc.pop("nlu", None)
    mongo_doc.pop("date", None)
    mongo_doc.pop("user_message", None)
    mongo_doc.pop("bot_message", None)

    mock_collection.find_one.return_value = mongo_doc

    result = await saver.get("t1")

    mock_collection.find_one.assert_awaited_once()
    # Should reconstruct a State and not be None
    assert isinstance(result, State)
    assert result.thread_id == "t1"


@pytest.mark.asyncio
async def test_get_all_returns_list_of_state_instances():
    mock_db = AsyncMock()
    mock_collection = AsyncMock()
    mock_cursor = AsyncMock()

    mock_db.get_collection.return_value = mock_collection
    mock_collection.find.return_value = mock_cursor
    mock_cursor.to_list.return_value = [
        State(thread_id="t1").to_dict(),
        State(thread_id="t1", context={"a": 1}).to_dict(),
    ]

    saver = MemorySaverMongo(mock_db)

    states = await saver.get_all("t1")

    mock_collection.find.assert_called_once()
    mock_cursor.to_list.assert_awaited_once()

    assert len(states) == 2
    assert all(isinstance(s, State) for s in states)
    assert states[1].context == {"a": 1}